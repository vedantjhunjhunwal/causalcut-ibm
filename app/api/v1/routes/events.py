"""Ingestion boundary — the trust boundary from the design doc's §3.1 diagram.

Order of operations is the whole design, and it is deliberate:

    validate -> tag -> PERSIST -> queue -> ack

We write to the append-only event store *before* enqueueing. That inversion
(most tutorials queue first) is what makes a full queue, a crashed consumer or
a restart survivable: the record is durable, so processing can be replayed. An
event that was accepted is never lost, only possibly late — and 'late' is
visible in /stats, whereas 'lost' is not.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import ValidationError

from app.api.deps import (
    CorrelationDep,
    DbDep,
    EventRepoDep,
    QueueDep,
    SettingsDep,
    require_api_key,
)
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.repositories import DeadLetterRepository
from app.schemas.canonical import SafetyEvent, SafetyEventIn
from app.schemas.enums import EventType, InformationClass, ProcessingStatus, ZoneId
from app.schemas.ingest import IngestAck, IngestBatchIn, IngestResult

log = get_logger(__name__)

router = APIRouter(prefix="/events", tags=["ingestion"])


async def _ingest_one(
    raw: SafetyEventIn,
    correlation_id: str,
    events: EventRepoDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> IngestResult:
    now = datetime.now(timezone.utc)

    # --- 1. Normalise + tag ------------------------------------------
    try:
        event: SafetyEvent = raw.to_canonical(
            correlation_id=correlation_id,
            default_window=timedelta(seconds=settings.default_validity_window_seconds),
        )
    except ValidationError as exc:
        return IngestResult(
            event_id=raw.event_id or uuid.uuid4(),
            status=ProcessingStatus.REJECTED,
            detail="; ".join(e["msg"] for e in exc.errors())[:500],
        )

    # --- 2. Clock sanity ---------------------------------------------
    if event.event_time > now + timedelta(seconds=settings.future_event_tolerance_seconds):
        return IngestResult(
            event_id=event.event_id,
            status=ProcessingStatus.REJECTED,
            detail="event_time is in the future beyond tolerance — check producer clock",
        )

    # Stale events are accepted, not dropped. A late reading is still evidence;
    # what matters is that downstream knows it cannot be trusted as current
    # (Appendix A: 'missing/stale sensor data' -> raise uncertainty).
    stale = event.is_stale(now)

    # --- 3. Persist (durability before dispatch) ----------------------
    stored = await events.append(event)
    if not stored:
        return IngestResult(
            event_id=event.event_id,
            status=ProcessingStatus.DUPLICATE,
            detail="event_id already present — idempotent no-op",
            stale=stale,
        )

    # --- 4. Dispatch --------------------------------------------------
    queued = await queue.put(event)
    return IngestResult(
        event_id=event.event_id,
        status=ProcessingStatus.ACCEPTED if queued else ProcessingStatus.QUEUE_FULL,
        detail=None if queued else "persisted; awaiting replay (queue saturated)",
        stale=stale,
    )


@router.post(
    "/ingest",
    response_model=IngestAck,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
    summary="Ingest one canonical safety event",
    description=(
        "Validates against the canonical schema, tags information class, writes "
        "to the append-only event store, then dispatches to the async queue. "
        "202 means durably persisted — not necessarily processed."
    ),
)
async def ingest_event(
    payload: SafetyEventIn,
    correlation_id: CorrelationDep,
    events: EventRepoDep,
    queue: QueueDep,
    settings: SettingsDep,
    response: Response,
) -> IngestAck:
    result = await _ingest_one(payload, correlation_id, events, queue, settings)
    if result.status is ProcessingStatus.REJECTED:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return IngestAck(
        correlation_id=correlation_id,
        accepted=int(result.status is ProcessingStatus.ACCEPTED),
        duplicates=int(result.status is ProcessingStatus.DUPLICATE),
        rejected=int(result.status is ProcessingStatus.REJECTED),
        queue_depth=queue.depth,
        results=[result],
    )


@router.post(
    "/ingest/batch",
    response_model=IngestAck,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
    summary="Ingest a batch of canonical safety events",
    description=(
        "Partial success is intentional: one malformed reading from one sensor "
        "must not reject the other fifteen sensors in the same poll cycle. Each "
        "event gets its own result row."
    ),
)
async def ingest_batch(
    payload: IngestBatchIn,
    correlation_id: CorrelationDep,
    events: EventRepoDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> IngestAck:
    results = [
        await _ingest_one(raw, correlation_id, events, queue, settings)
        for raw in payload.events
    ]
    ack = IngestAck(
        correlation_id=correlation_id,
        accepted=sum(r.status is ProcessingStatus.ACCEPTED for r in results),
        duplicates=sum(r.status is ProcessingStatus.DUPLICATE for r in results),
        rejected=sum(r.status is ProcessingStatus.REJECTED for r in results),
        queue_depth=queue.depth,
        results=results,
    )
    log.info(
        "batch ingested",
        extra={"accepted": ack.accepted, "duplicates": ack.duplicates,
               "rejected": ack.rejected, "queue_depth": ack.queue_depth},
    )
    return ack


@router.get("/{event_id}", summary="Fetch one event from the append-only store")
async def get_event(event_id: uuid.UUID, events: EventRepoDep) -> dict:
    row = await events.get(event_id)
    if row is None:
        raise NotFoundError(f"event {event_id} not found")
    return row


@router.get("", summary="Recent events, newest first")
async def list_events(
    events: EventRepoDep,
    limit: int = Query(50, ge=1, le=500),
    zone_id: ZoneId | None = None,
    event_type: EventType | None = None,
    information_class: InformationClass | None = None,
) -> dict:
    rows = await events.list_recent(
        limit=limit,
        zone_id=str(zone_id) if zone_id else None,
        event_type=str(event_type) if event_type else None,
        information_class=str(information_class) if information_class else None,
    )
    return {"count": len(rows), "events": rows}


@router.get("/dead-letter/list", summary="Events that failed downstream processing")
async def dead_letter(db: DbDep, limit: int = Query(50, ge=1, le=500)) -> dict:
    rows = await DeadLetterRepository(db).list(limit)
    return {"count": len(rows), "dead_letter": rows}

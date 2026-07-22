"""Shared ingestion service — the single ingestion implementation.

Both ``POST /api/v1/events/ingest`` and the scenario runner call
``ingest_canonical_event`` so the trust-boundary order is identical everywhere:

    validate -> clock check -> PERSIST (append-only store) -> queue -> ack

Persisting before enqueueing is what makes a full queue, a crashed consumer or
a restart survivable. This module holds that logic once; the route is a thin
HTTP wrapper over it and the scenario runner reuses it directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from app.schemas.canonical import SafetyEvent, SafetyEventIn
from app.schemas.enums import ProcessingStatus
from app.schemas.ingest import IngestResult


async def ingest_canonical_event(
    event: SafetyEvent,
    events_repo,
    queue,
    settings,
) -> IngestResult:
    """Persist then enqueue an already-canonical event.

    Used by the scenario runner, whose events come straight out of the trained
    model services and are canonical by construction.
    """
    now = datetime.now(timezone.utc)

    if event.event_time > now + timedelta(seconds=settings.future_event_tolerance_seconds):
        return IngestResult(
            event_id=event.event_id,
            status=ProcessingStatus.REJECTED,
            detail="event_time is in the future beyond tolerance — check producer clock",
        )

    stale = event.is_stale(now)

    stored = await events_repo.append(event)
    if not stored:
        return IngestResult(
            event_id=event.event_id,
            status=ProcessingStatus.DUPLICATE,
            detail="event_id already present — idempotent no-op",
            stale=stale,
        )

    queued = await queue.put(event)
    return IngestResult(
        event_id=event.event_id,
        status=ProcessingStatus.ACCEPTED if queued else ProcessingStatus.QUEUE_FULL,
        detail=None if queued else "persisted; awaiting replay (queue saturated)",
        stale=stale,
    )


async def ingest_raw_event(
    raw: SafetyEventIn,
    correlation_id: str,
    events_repo,
    queue,
    settings,
) -> IngestResult:
    """Normalise + tag an inbound wire event, then ingest it."""
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

    return await ingest_canonical_event(event, events_repo, queue, settings)

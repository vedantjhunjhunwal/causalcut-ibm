"""Consumers: canonical event -> plant-state projection.

Day 1 scope is deliberately narrow. This consumer maintains the Plant-State
Store (sensor_latest, worker_zones, permits, barriers). It does NOT compute
risk, activate hyperedges or select interventions — those modules subscribe to
the same queue later (§3.1). Keeping the projection dumb keeps it correct.

Retry policy: bounded retries, then dead-letter. A consumer that retries
forever is a consumer that silently stops processing everything behind it.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from app.core.logging import correlation_id_ctx, get_logger
from app.db.repositories import (
    DeadLetterRepository,
    EventRepository,
    PermitRepository,
    SensorTelemetryRepository,
    WorkerZoneRepository,
)
from app.db.session import Database
from app.queue.event_queue import EventQueue, QueuedEvent
from app.schemas.canonical import SafetyEvent
from app.schemas.enums import EventType

log = get_logger(__name__)

_SENSOR_KIND_BY_PREFIX = {
    "GS": "gas", "TEMP": "temperature", "VENT": "flow", "PRESS": "pressure",
    "FS": "flow", "TS": "temperature", "PS": "pressure", "VS": "vibration",
    "EPS": "power", "CE": "efficiency",
}


def _sensor_kind(sensor_id: str) -> str:
    prefix = sensor_id.split("-")[0].upper()
    return _SENSOR_KIND_BY_PREFIX.get(prefix, "unknown")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class StateProjector:
    """Applies one canonical event to the plant-state store."""

    def __init__(self, db: Database) -> None:
        self.telemetry = SensorTelemetryRepository(db)
        self.workers = WorkerZoneRepository(db)
        self.permits = PermitRepository(db)
        self.db = db

    async def apply(self, e: SafetyEvent) -> None:
        handler = {
            EventType.GAS_ANOMALY: self._sensor,
            EventType.UTILITY_CONDITION: self._sensor,
            EventType.SENSOR_DRIFT: self._sensor_drift,
            EventType.EQUIPMENT_FAILURE: self._asset,
            EventType.PPE_VIOLATION: self._worker,
            EventType.WORKER_PRESENCE: self._worker,
            EventType.PERMIT_STATUS: self._permit,
            EventType.PERMIT_CONFLICT: self._noop,
            EventType.SHIFT_INCONSISTENCY: self._noop,
            EventType.BARRIER_STATUS: self._barrier,
            EventType.COMPOUND_RISK: self._noop,
        }.get(e.event_type, self._noop)
        await handler(e)

    async def _noop(self, e: SafetyEvent) -> None:
        return

    async def _sensor(self, e: SafetyEvent) -> None:
        sensor_id = e.value.get("sensor_id")
        if not sensor_id:
            return
        value = e.value.get("concentration_ppm")
        if value is None:
            value = e.value.get("value")
        await self.telemetry.record(
            sensor_id=sensor_id,
            zone_id=str(e.zone_id),
            sensor_kind=e.value.get("sensor_kind") or _sensor_kind(sensor_id),
            reading_time=_iso(e.event_time),
            event_id=str(e.event_id),
            value_num=float(value) if isinstance(value, (int, float)) else None,
            unit=e.value.get("unit", "ppm" if "concentration_ppm" in e.value else None),
            payload=e.value,
            quality=e.confidence,
            stale=e.is_stale(),
            drift_flag=bool(e.value.get("drift_detected", False)),
            factory_id=e.factory_id,
            synthetic=e.synthetic_flag,
        )

    async def _sensor_drift(self, e: SafetyEvent) -> None:
        sensor_id = e.value.get("sensor_id")
        if not sensor_id:
            return
        await self.db.execute(
            "UPDATE sensor_latest SET drift_flag = 1, updated_at = ? WHERE sensor_id = ?",
            (_iso(datetime.now(timezone.utc)), sensor_id),
        )

    async def _asset(self, e: SafetyEvent) -> None:
        # Asset condition table lands with the equipment-failure module; the
        # event is already durable, so nothing is lost by deferring.
        return

    async def _worker(self, e: SafetyEvent) -> None:
        ppe = e.value.get("ppe", {})
        if e.event_type is EventType.PPE_VIOLATION and not ppe:
            missing = e.value.get("missing", [])
            ppe = {item: False for item in missing}
        await self.workers.upsert_presence(
            worker_id=e.worker_id,  # validator guarantees non-null here
            zone_id=str(e.zone_id) if e.value.get("present", True) else None,
            event_time=_iso(e.event_time),
            event_id=str(e.event_id),
            ppe=ppe,
            confidence=e.confidence,
            camera_id=e.value.get("camera_id"),
            factory_id=e.factory_id,
            synthetic=e.synthetic_flag,
        )

    async def _permit(self, e: SafetyEvent) -> None:
        v = e.value
        if not v.get("permit_id"):
            return
        await self.permits.upsert(
            {
                "permit_id": v["permit_id"],
                "factory_id": e.factory_id,
                "zone_id": str(e.zone_id),
                "permit_type": v.get("permit_type", "hot_work"),
                "status": v.get("status", "active"),
                "issued_to": v.get("issued_to"),
                "issued_by": v.get("issued_by"),
                "valid_from": v.get("valid_from", _iso(e.event_time)),
                "valid_to": v.get("valid_to", _iso(e.expires_at)),
                "conditions": v.get("conditions", {}),
                "information_class": str(e.information_class),
                "synthetic_flag": e.synthetic_flag,
                "last_event_id": str(e.event_id),
            }
        )

    async def _barrier(self, e: SafetyEvent) -> None:
        v = e.value
        if not v.get("barrier_id"):
            return
        await self.db.execute(
            """INSERT INTO barriers (barrier_id, zone_id, barrier_type, status,
                   updated_at, last_event_id)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(barrier_id) DO UPDATE SET
                   status = excluded.status,
                   updated_at = excluded.updated_at,
                   last_event_id = excluded.last_event_id""",
            (
                v["barrier_id"], str(e.zone_id), v.get("barrier_type", "unknown"),
                v.get("status", "unknown"),
                _iso(datetime.now(timezone.utc)), str(e.event_id),
            ),
        )


class ConsumerPool:
    def __init__(
        self,
        queue: EventQueue,
        db: Database,
        count: int = 2,
        max_retries: int = 3,
        risk_engine: "object | None" = None,
    ) -> None:
        self.queue = queue
        self.db = db
        self.count = count
        self.max_retries = max_retries
        self.projector = StateProjector(db)
        self.events = EventRepository(db)
        self.dlq = DeadLetterRepository(db)
        # Optional analytical subscriber. It runs *after* the durable projection
        # and is fully isolated: a risk-engine error can never fail or retry the
        # state projection (see _handle). Kept as a plain object to avoid a hard
        # import cycle between queue and engine.
        self.risk_engine = risk_engine
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._run(f"consumer-{i}"), name=f"consumer-{i}")
            for i in range(self.count)
        ]
        log.info("consumer pool started", extra={"consumers": self.count})

    async def stop(self) -> None:
        await self.queue.drain()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        log.info("consumer pool stopped")

    async def _run(self, name: str) -> None:
        while True:
            try:
                item = await self.queue.get()
            except asyncio.CancelledError:
                return
            try:
                await self._handle(name, item)
            except asyncio.CancelledError:
                self.queue.task_done()
                return
            except Exception:  # a consumer must never die of one bad event
                log.exception("consumer loop error", extra={"consumer": name})
            finally:
                self.queue.task_done()

    async def _handle(self, name: str, item: QueuedEvent) -> None:
        e = item.event
        token = correlation_id_ctx.set(e.correlation_id)
        try:
            await self.projector.apply(e)
            await self.events.mark_processed(e.event_id)
            self.queue.counters.processed += 1
            log.debug(
                "event projected",
                extra={"event_id": str(e.event_id), "event_type": str(e.event_type),
                       "consumer": name},
            )
            # Analytical subscriber runs after the durable projection. Isolated:
            # its failure must not dead-letter or retry a correctly-projected
            # event, so we catch and log rather than propagate.
            if self.risk_engine is not None:
                try:
                    self.risk_engine.apply_canonical(e)
                except Exception:  # pragma: no cover - defensive
                    log.exception(
                        "risk engine failed on event (projection unaffected)",
                        extra={"event_id": str(e.event_id)},
                    )
        except Exception as exc:
            self.queue.counters.failed += 1
            if item.attempt < self.max_retries:
                self.queue.counters.retried += 1
                await asyncio.sleep(0.1 * 2 ** item.attempt)  # backoff
                await self.queue.put(e, attempt=item.attempt + 1)
                log.warning(
                    "projection failed; retrying",
                    extra={"event_id": str(e.event_id), "attempt": item.attempt,
                           "error": str(exc)},
                )
            else:
                await self.dlq.record(e, name, item.attempt, exc)
                self.queue.counters.dead_lettered += 1
                log.error(
                    "projection failed; dead-lettered",
                    extra={"event_id": str(e.event_id), "attempts": item.attempt,
                           "error": str(exc)},
                )
        finally:
            correlation_id_ctx.reset(token)

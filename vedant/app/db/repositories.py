"""Repositories — the only code allowed to write SQL.

Keeping SQL here (rather than scattered through routes) is what makes the
SQLite -> PostgreSQL swap in §9 a contained change instead of a rewrite.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.db.session import Database
from app.schemas.canonical import SafetyEvent

_EVENT_INSERT = """
INSERT OR IGNORE INTO events (
    event_id, factory_id, zone_id, event_type, worker_id, asset_id,
    event_time, ingest_time, expires_at, validity_window_s, value_json,
    severity, confidence, uncertainty, source, model_version, provenance,
    information_class, synthetic_flag, schema_version, correlation_id,
    payload_hash, processed
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
"""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _now() -> str:
    return _iso(datetime.now(timezone.utc))


class EventRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _params(e: SafetyEvent) -> tuple:
        return (
            str(e.event_id), e.factory_id, str(e.zone_id), str(e.event_type),
            e.worker_id, e.asset_id, _iso(e.event_time), _iso(e.ingest_time),
            _iso(e.expires_at), int(e.validity_window.total_seconds()),
            json.dumps(e.value, default=str), e.severity, e.confidence,
            e.uncertainty, e.source, e.model_version, e.provenance,
            str(e.information_class), int(e.synthetic_flag), e.schema_version,
            e.correlation_id, e.payload_hash(),
        )

    async def append(self, event: SafetyEvent) -> bool:
        """Returns True if newly stored, False if event_id already existed.
        Idempotency lives here — consumers can replay freely (§3.1)."""
        rowcount = await self.db.execute(_EVENT_INSERT, self._params(event))
        return rowcount > 0

    async def exists(self, event_id: uuid.UUID) -> bool:
        row = await self.db.fetch_one(
            "SELECT 1 AS ok FROM events WHERE event_id = ?", (str(event_id),)
        )
        return row is not None

    async def get(self, event_id: uuid.UUID) -> dict | None:
        return await self.db.fetch_one(
            "SELECT * FROM events WHERE event_id = ?", (str(event_id),)
        )

    async def list_recent(
        self,
        limit: int = 50,
        zone_id: str | None = None,
        event_type: str | None = None,
        information_class: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if zone_id:
            sql += " AND zone_id = ?"
            params.append(zone_id)
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        if information_class:
            sql += " AND information_class = ?"
            params.append(information_class)
        sql += " ORDER BY event_time DESC LIMIT ?"
        params.append(limit)
        return await self.db.fetch_all(sql, params)

    async def mark_processed(self, event_id: uuid.UUID) -> None:
        await self.db.execute(
            "UPDATE events SET processed = 1 WHERE event_id = ?", (str(event_id),)
        )

    async def counts_by_class(self) -> dict[str, int]:
        rows = await self.db.fetch_all(
            "SELECT information_class, COUNT(*) AS n FROM events "
            "GROUP BY information_class"
        )
        return {r["information_class"]: r["n"] for r in rows}


class DeadLetterRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def record(
        self,
        event: SafetyEvent,
        consumer: str,
        attempt: int,
        error: BaseException,
    ) -> None:
        await self.db.execute(
            """INSERT INTO dead_letter
               (event_id, correlation_id, failed_at, consumer, attempt,
                error_type, error_detail, payload_json)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                str(event.event_id), event.correlation_id, _now(), consumer,
                attempt, type(error).__name__, str(error)[:2000],
                event.model_dump_json(),
            ),
        )

    async def list(self, limit: int = 50) -> list[dict]:
        return await self.db.fetch_all(
            "SELECT * FROM dead_letter ORDER BY id DESC LIMIT ?", (limit,)
        )


class PermitRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def upsert(self, permit: dict) -> None:
        await self.db.execute(
            """INSERT INTO permits (permit_id, factory_id, zone_id, permit_type,
                   status, issued_to, issued_by, valid_from, valid_to,
                   conditions_json, information_class, synthetic_flag,
                   updated_at, last_event_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(permit_id) DO UPDATE SET
                   status         = excluded.status,
                   zone_id        = excluded.zone_id,
                   valid_to       = excluded.valid_to,
                   conditions_json= excluded.conditions_json,
                   updated_at     = excluded.updated_at,
                   last_event_id  = excluded.last_event_id""",
            (
                permit["permit_id"], permit.get("factory_id", "steelforge-001"),
                permit["zone_id"], permit["permit_type"], permit["status"],
                permit.get("issued_to"), permit.get("issued_by"),
                permit["valid_from"], permit["valid_to"],
                json.dumps(permit.get("conditions", {})),
                permit.get("information_class", "S"),
                int(permit.get("synthetic_flag", True)),
                _now(), permit.get("last_event_id"),
            ),
        )

    async def active_in_zone(self, zone_id: str) -> list[dict]:
        return await self.db.fetch_all(
            """SELECT * FROM permits
               WHERE zone_id = ? AND status = 'active'
                 AND valid_from <= ? AND valid_to >= ?""",
            (zone_id, _now(), _now()),
        )

    async def all_active(self) -> list[dict]:
        return await self.db.fetch_all(
            "SELECT * FROM permits WHERE status = 'active' ORDER BY valid_to"
        )

    async def set_status(self, permit_id: str, status: str) -> int:
        return await self.db.execute(
            "UPDATE permits SET status = ?, updated_at = ? WHERE permit_id = ?",
            (status, _now(), permit_id),
        )


class WorkerZoneRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def upsert_presence(
        self,
        worker_id: str,
        zone_id: str | None,
        event_time: str,
        event_id: str,
        ppe: dict | None = None,
        confidence: float | None = None,
        camera_id: str | None = None,
        factory_id: str = "steelforge-001",
        synthetic: bool = False,
    ) -> None:
        ppe = ppe or {}
        compliant = int(all(bool(v) for v in ppe.values())) if ppe else 1
        await self.db.execute(
            """INSERT INTO worker_zones (worker_id, factory_id, zone_id,
                   entered_at, last_seen_at, ppe_json, ppe_compliant,
                   detection_confidence, camera_id, information_class,
                   synthetic_flag, updated_at, last_event_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(worker_id) DO UPDATE SET
                   zone_id              = excluded.zone_id,
                   last_seen_at         = excluded.last_seen_at,
                   ppe_json             = excluded.ppe_json,
                   ppe_compliant        = excluded.ppe_compliant,
                   detection_confidence = excluded.detection_confidence,
                   camera_id            = excluded.camera_id,
                   updated_at           = excluded.updated_at,
                   last_event_id        = excluded.last_event_id,
                   entered_at = CASE
                       WHEN worker_zones.zone_id IS excluded.zone_id
                       THEN worker_zones.entered_at
                       ELSE excluded.entered_at END""",
            (
                worker_id, factory_id, zone_id, event_time, event_time,
                json.dumps(ppe), compliant, confidence, camera_id,
                "S" if synthetic else "M", int(synthetic), _now(), event_id,
            ),
        )
        await self.db.execute(
            """INSERT INTO worker_zone_history (worker_id, zone_id, event_time, event_id)
               VALUES (?,?,?,?)""",
            (worker_id, zone_id, event_time, event_id),
        )

    async def in_zone(self, zone_id: str) -> list[dict]:
        return await self.db.fetch_all(
            "SELECT * FROM worker_zones WHERE zone_id = ? ORDER BY worker_id",
            (zone_id,),
        )

    async def non_compliant(self) -> list[dict]:
        return await self.db.fetch_all(
            "SELECT * FROM worker_zones WHERE ppe_compliant = 0 AND zone_id IS NOT NULL"
        )

    async def all(self) -> list[dict]:
        return await self.db.fetch_all(
            "SELECT * FROM worker_zones ORDER BY worker_id"
        )


class SensorTelemetryRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def record(
        self,
        sensor_id: str,
        zone_id: str,
        sensor_kind: str,
        reading_time: str,
        event_id: str,
        value_num: float | None = None,
        unit: str | None = None,
        payload: dict | None = None,
        quality: float = 1.0,
        stale: bool = False,
        drift_flag: bool = False,
        factory_id: str = "steelforge-001",
        synthetic: bool = False,
    ) -> None:
        await self.db.execute(
            """INSERT OR IGNORE INTO sensor_telemetry
                   (sensor_id, factory_id, zone_id, sensor_kind, reading_time,
                    value_num, unit, value_json, quality, stale, drift_flag,
                    information_class, synthetic_flag, event_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sensor_id, factory_id, zone_id, sensor_kind, reading_time,
                value_num, unit, json.dumps(payload or {}, default=str),
                quality, int(stale), int(drift_flag),
                "S" if synthetic else "M", int(synthetic), event_id,
            ),
        )
        # Latest-value projection: only move forward in time, never backward.
        # This is the out-of-order guard the design doc asks for at ingest.
        await self.db.execute(
            """INSERT INTO sensor_latest (sensor_id, zone_id, sensor_kind,
                   reading_time, value_num, unit, stale, drift_flag,
                   event_id, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(sensor_id) DO UPDATE SET
                   zone_id      = excluded.zone_id,
                   reading_time = excluded.reading_time,
                   value_num    = excluded.value_num,
                   unit         = excluded.unit,
                   stale        = excluded.stale,
                   drift_flag   = excluded.drift_flag,
                   event_id     = excluded.event_id,
                   updated_at   = excluded.updated_at
               WHERE excluded.reading_time > sensor_latest.reading_time""",
            (
                sensor_id, zone_id, sensor_kind, reading_time, value_num, unit,
                int(stale), int(drift_flag), event_id, _now(),
            ),
        )

    async def latest_for_zone(self, zone_id: str) -> list[dict]:
        return await self.db.fetch_all(
            "SELECT * FROM sensor_latest WHERE zone_id = ? ORDER BY sensor_id",
            (zone_id,),
        )

    async def history(self, sensor_id: str, limit: int = 100) -> list[dict]:
        return await self.db.fetch_all(
            """SELECT * FROM sensor_telemetry WHERE sensor_id = ?
               ORDER BY reading_time DESC LIMIT ?""",
            (sensor_id, limit),
        )

    async def mark_stale_beyond(self, cutoff_iso: str) -> int:
        """Validity-window expiry sweep (Appendix A: missing/stale sensor data)."""
        return await self.db.execute(
            "UPDATE sensor_latest SET stale = 1 WHERE reading_time < ? AND stale = 0",
            (cutoff_iso,),
        )

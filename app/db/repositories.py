"""Repositories — the only code allowed to write SQL.

Keeping DB access here (rather than scattered through routes) is what makes the
SQLite -> PostgreSQL swap in §9 a contained change instead of a rewrite.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import httpcore

from app.db.session import Database
from app.schemas.canonical import SafetyEvent
from app.core.logging import get_logger

log = get_logger(__name__)

# WinError 10035 = WSAEWOULDBLOCK: the Windows socket is in non-blocking mode
# and couldn't service the request immediately. One immediate retry is always
# sufficient for a synchronous supabase-py / httpx client running in a thread.
_WSAEWOULDBLOCK = 10035

# Transient HTTP transport exceptions that justify a retry.  These cover:
#   • httpx.RemoteProtocolError  — HTTP/2 GOAWAY / ConnectionTerminated
#   • httpx.NetworkError         — ConnectError, ReadError, WriteError, CloseError
#                                  (also catches WinError 10035 wrapped by httpx)
#   • httpx.ReadTimeout          — server held the connection too long
#   • httpcore.RemoteProtocolError, httpcore.NetworkError, ConnectionNotAvailable
#     (lower-level equivalents surfaced before httpx wraps them)
_TRANSIENT_HTTP_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.NetworkError,            # parent of Connect/Read/Write/CloseError
    httpx.ReadTimeout,
    httpcore.RemoteProtocolError,
    httpcore.NetworkError,         # parent of httpcore Connect/Read/Write errors
    httpcore.ConnectionNotAvailable,
)


def _is_wsaewouldblock(exc: BaseException) -> bool:
    """Return True if *exc* or any chained cause is WinError 10035."""
    cur: BaseException | None = exc
    while cur is not None:
        if isinstance(cur, OSError):
            if getattr(cur, 'winerror', None) == _WSAEWOULDBLOCK or cur.errno == _WSAEWOULDBLOCK:
                return True
        cur = cur.__cause__ or cur.__context__
        if cur is exc:          # guard against reference loops
            break
    return False


async def _supabase_call(fn, *args, max_retries: int = 4, **kwargs):
    """Run a blocking Supabase call in a thread, retrying on transient errors.

    Retried conditions:
      • WinError 10035 (WSAEWOULDBLOCK) — Windows non-blocking socket, whether
        raised directly as ``OSError`` or wrapped inside an ``httpx`` exception.
      • HTTP/2 stale-connection GOAWAY (``RemoteProtocolError``)
      • TCP-level connect / read / write failures
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except _TRANSIENT_HTTP_ERRORS as exc:
            last_exc = exc
            log.warning(
                "transient Supabase transport error, retrying",
                extra={"attempt": attempt + 1, "max": max_retries,
                       "error": str(exc)[:200]},
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5 * (2 ** attempt))   # 0.5 s, 1 s, 2 s
                continue
            raise
        except OSError as exc:
            if _is_wsaewouldblock(exc):
                last_exc = exc
                log.warning(
                    "WSAEWOULDBLOCK on Supabase call, retrying",
                    extra={"attempt": attempt + 1, "max": max_retries},
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
            raise
    raise last_exc  # type: ignore[misc]

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _now() -> str:
    return _iso(datetime.now(timezone.utc))


class EventRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _params(self, e: SafetyEvent) -> dict:
        return {
            "event_id": str(e.event_id),
            "factory_id": e.factory_id,
            "zone_id": str(e.zone_id),
            "event_type": str(e.event_type),
            "worker_id": e.worker_id,
            "asset_id": e.asset_id,
            "event_time": _iso(e.event_time),
            "ingest_time": _iso(e.ingest_time),
            "expires_at": _iso(e.expires_at),
            "validity_window_s": int(e.validity_window.total_seconds()),
            "value_json": json.dumps(e.value, default=str),
            "severity": e.severity,
            "confidence": e.confidence,
            "uncertainty": e.uncertainty,
            "source": e.source,
            "model_version": e.model_version,
            "provenance": e.provenance,
            "information_class": str(e.information_class),
            "synthetic_flag": int(e.synthetic_flag),
            "schema_version": e.schema_version,
            "correlation_id": e.correlation_id,
            "payload_hash": e.payload_hash(),
            "processed": 0
        }

    async def append(self, event: SafetyEvent) -> bool:
        """Returns True if newly stored, False if event_id already existed."""
        def _exec():
            try:
                self.db.client.table('events').insert(self._params(event)).execute()
                return True
            except Exception as e:
                if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                    return False
                raise
        return await _supabase_call(_exec)

    async def exists(self, event_id: uuid.UUID) -> bool:
        def _exec():
            res = self.db.client.table('events').select('event_id').eq('event_id', str(event_id)).execute()
            return len(res.data) > 0
        return await _supabase_call(_exec)

    async def get(self, event_id: uuid.UUID) -> dict | None:
        def _exec():
            res = self.db.client.table('events').select('*').eq('event_id', str(event_id)).execute()
            return res.data[0] if res.data else None
        return await _supabase_call(_exec)

    async def list_recent(
        self,
        limit: int = 50,
        zone_id: str | None = None,
        event_type: str | None = None,
        information_class: str | None = None,
    ) -> list[dict]:
        def _exec():
            query = self.db.client.table('events').select('*')
            if zone_id:
                query = query.eq('zone_id', zone_id)
            if event_type:
                query = query.eq('event_type', event_type)
            if information_class:
                query = query.eq('information_class', information_class)
            res = query.order('event_time', desc=True).limit(limit).execute()
            return res.data
        return await _supabase_call(_exec)

    async def mark_processed(self, event_id: uuid.UUID) -> None:
        def _exec():
            try:
                self.db.client.table('events').update({'processed': 1}).eq('event_id', str(event_id)).execute()
            except Exception:
                pass
        try:
            asyncio.create_task(_supabase_call(_exec, max_retries=1))
        except RuntimeError:
            pass

    async def counts_by_class(self) -> dict[str, int]:
        def _exec():
            res = self.db.client.table('events').select('information_class').execute()
            counts = {}
            for row in res.data:
                c = row.get('information_class')
                counts[c] = counts.get(c, 0) + 1
            return counts
        return await _supabase_call(_exec)


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
        def _exec():
            data = {
                "event_id": str(event.event_id),
                "correlation_id": event.correlation_id,
                "failed_at": _now(),
                "consumer": consumer,
                "attempt": attempt,
                "error_type": type(error).__name__,
                "error_detail": str(error)[:2000],
                "payload_json": event.model_dump_json()
            }
            self.db.client.table('dead_letter').insert(data).execute()
        await _supabase_call(_exec)

    async def list(self, limit: int = 50) -> list[dict]:
        def _exec():
            res = self.db.client.table('dead_letter').select('*').order('id', desc=True).limit(limit).execute()
            return res.data
        return await _supabase_call(_exec)


class PermitRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def upsert(self, permit: dict) -> None:
        def _exec():
            data = {
                "permit_id": permit["permit_id"],
                "factory_id": permit.get("factory_id", "00000000-0000-0000-0000-000000000001"),
                "zone_id": permit["zone_id"],
                "permit_type": permit["permit_type"],
                "status": permit["status"],
                "issued_to": permit.get("issued_to"),
                "issued_by": permit.get("issued_by"),
                "valid_from": permit["valid_from"],
                "valid_to": permit["valid_to"],
                "conditions_json": json.dumps(permit.get("conditions", {})),
                "information_class": permit.get("information_class", "S"),
                "synthetic_flag": int(permit.get("synthetic_flag", True)),
                "updated_at": _now(),
                "last_event_id": permit.get("last_event_id")
            }
            self.db.client.table('permits').upsert(data).execute()
        await _supabase_call(_exec)

    async def active_in_zone(self, zone_id: str) -> list[dict]:
        def _exec():
            now = _now()
            res = self.db.client.table('permits').select('*').eq('zone_id', zone_id).eq('status', 'active').lte('valid_from', now).gte('valid_to', now).execute()
            return res.data
        return await _supabase_call(_exec)

    async def all_active(self) -> list[dict]:
        def _exec():
            res = self.db.client.table('permits').select('*').eq('status', 'active').order('valid_to').execute()
            return res.data
        return await _supabase_call(_exec)

    async def set_status(self, permit_id: str, status: str) -> int:
        def _exec():
            res = self.db.client.table('permits').update({'status': status, 'updated_at': _now()}).eq('permit_id', permit_id).execute()
            return len(res.data)
        return await _supabase_call(_exec)


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
        factory_id: str = "00000000-0000-0000-0000-000000000001",
        synthetic: bool = False,
    ) -> None:
        ppe = ppe or {}
        compliant = int(all(bool(v) for v in ppe.values())) if ppe else 1
        
        def _exec():
            existing = self.db.client.table('worker_zones').select('zone_id', 'entered_at').eq('worker_id', worker_id).execute()
            
            entered_at = event_time
            if existing.data:
                old = existing.data[0]
                if old.get('zone_id') == zone_id:
                    entered_at = old.get('entered_at')
                    
            data = {
                "worker_id": worker_id,
                "factory_id": factory_id,
                "zone_id": zone_id,
                "entered_at": entered_at,
                "last_seen_at": event_time,
                "ppe_json": json.dumps(ppe),
                "ppe_compliant": compliant,
                "detection_confidence": confidence,
                "camera_id": camera_id,
                "information_class": "S" if synthetic else "M",
                "synthetic_flag": int(synthetic),
                "updated_at": _now(),
                "last_event_id": event_id
            }
            self.db.client.table('worker_zones').upsert(data).execute()
            
            # History insert is non-critical (audit trail); must not block
            # the projection if the table hasn't been migrated yet.
            try:
                hist_data = {
                    "worker_id": worker_id,
                    "zone_id": zone_id,
                    "event_time": event_time,
                    "event_id": event_id
                }
                self.db.client.table('worker_zone_history').insert(hist_data).execute()
            except Exception as hist_err:
                log.warning(
                    "worker_zone_history insert failed (non-critical)",
                    extra={"worker_id": worker_id, "error": str(hist_err)},
                )
        await _supabase_call(_exec)

    async def in_zone(self, zone_id: str) -> list[dict]:
        def _exec():
            res = self.db.client.table('worker_zones').select('*').eq('zone_id', zone_id).order('worker_id').execute()
            return res.data
        return await _supabase_call(_exec)

    async def non_compliant(self) -> list[dict]:
        def _exec():
            res = self.db.client.table('worker_zones').select('*').eq('ppe_compliant', 0).not_('zone_id', 'is', 'null').execute()
            return res.data
        return await _supabase_call(_exec)

    async def all(self) -> list[dict]:
        def _exec():
            res = self.db.client.table('worker_zones').select('*').order('worker_id').execute()
            return res.data
        return await _supabase_call(_exec)


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
        factory_id: str = "00000000-0000-0000-0000-000000000001",
        synthetic: bool = False,
    ) -> None:
        def _exec():
            tel_data = {
                "sensor_id": sensor_id,
                "factory_id": factory_id,
                "zone_id": zone_id,
                "sensor_kind": sensor_kind,
                "reading_time": reading_time,
                "value_num": value_num,
                "unit": unit,
                "value_json": json.dumps(payload or {}, default=str),
                "quality": quality,
                "stale": int(stale),
                "drift_flag": int(drift_flag),
                "information_class": "S" if synthetic else "M",
                "synthetic_flag": int(synthetic),
                "event_id": event_id
            }
            try:
                self.db.client.table('sensor_telemetry').insert(tel_data).execute()
            except Exception:
                pass 

            existing = self.db.client.table('sensor_latest').select('reading_time').eq('sensor_id', sensor_id).execute()
            should_update = True
            if existing.data:
                if existing.data[0].get('reading_time') >= reading_time:
                    should_update = False
            
            if should_update:
                lat_data = {
                    "sensor_id": sensor_id,
                    "factory_id": factory_id,
                    "zone_id": zone_id,
                    "sensor_kind": sensor_kind,
                    "reading_time": reading_time,
                    "value_num": value_num,
                    "unit": unit,
                    "stale": int(stale),
                    "drift_flag": int(drift_flag),
                    "event_id": event_id,
                    "updated_at": _now()
                }
                self.db.client.table('sensor_latest').upsert(lat_data).execute()
        await _supabase_call(_exec)

    async def latest_for_zone(self, zone_id: str) -> list[dict]:
        def _exec():
            res = self.db.client.table('sensor_latest').select('*').eq('zone_id', zone_id).order('sensor_id').execute()
            return res.data
        return await _supabase_call(_exec)

    async def history(self, sensor_id: str, limit: int = 100) -> list[dict]:
        def _exec():
            res = self.db.client.table('sensor_telemetry').select('*').eq('sensor_id', sensor_id).order('reading_time', desc=True).limit(limit).execute()
            return res.data
        return await _supabase_call(_exec)

    async def mark_stale_beyond(self, cutoff_iso: str) -> int:
        def _exec():
            res = self.db.client.table('sensor_latest').update({'stale': 1}).lt('reading_time', cutoff_iso).eq('stale', 0).execute()
            return len(res.data)
        return await _supabase_call(_exec)

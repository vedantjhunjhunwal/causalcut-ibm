"""Plant-State Store reads (design doc §5.2).

Read-only by construction. State here is a projection of the event store —
nothing mutates it except a consumer replaying a canonical event. That is what
keeps the audit trail total: if the console shows it, an event caused it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.api.deps import (
    PermitRepoDep,
    SettingsDep,
    TelemetryRepoDep,
    WorkerRepoDep,
)
from app.schemas.enums import ZoneId

router = APIRouter(prefix="/state", tags=["plant-state"])


@router.get("/zones/{zone_id}", summary="Current state of one zone")
async def zone_state(
    zone_id: ZoneId,
    permits: PermitRepoDep,
    workers: WorkerRepoDep,
    telemetry: TelemetryRepoDep,
    settings: SettingsDep,
) -> dict:
    zone = str(zone_id)
    sensors = await telemetry.latest_for_zone(zone)
    present = await workers.in_zone(zone)
    active_permits = await permits.active_in_zone(zone)

    return {
        "state_id": None,
        "factory_id": settings.factory_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "zone_id": zone,
        "sensor_readings": [
            {
                "sensor_id": s["sensor_id"],
                "kind": s["sensor_kind"],
                "value": s["value_num"],
                "unit": s["unit"],
                "reading_time": s["reading_time"],
                "stale": bool(s["stale"]),
                "drift": bool(s["drift_flag"]),
                "info_class": "M",
            }
            for s in sensors
        ],
        "workers_present": [
            {
                "worker_id": w["worker_id"],
                "ppe": json.loads(w["ppe_json"]),
                "ppe_compliant": bool(w["ppe_compliant"]),
                "last_seen_at": w["last_seen_at"],
                "info_class": w["information_class"],
            }
            for w in present
        ],
        "active_permits": [
            {
                "permit_id": p["permit_id"],
                "type": p["permit_type"],
                "valid_to": p["valid_to"],
                "info_class": p["information_class"],
            }
            for p in active_permits
        ],
        # risk_score is [P] and arrives with the hypergraph engine — it is
        # deliberately absent rather than defaulted to a comforting 0.0.
        "risk_score": None,
        "risk_info_class": "P",
        "schema_version": "1.0.0",
    }


@router.get("/permits", summary="All active permits")
async def list_permits(permits: PermitRepoDep) -> dict:
    rows = await permits.all_active()
    return {"count": len(rows), "permits": rows}


@router.get("/workers", summary="Worker zone occupancy and PPE status")
async def list_workers(
    workers: WorkerRepoDep,
    non_compliant_only: bool = Query(False),
) -> dict:
    rows = await (workers.non_compliant() if non_compliant_only else workers.all())
    for r in rows:
        r["ppe"] = json.loads(r.pop("ppe_json"))
    return {"count": len(rows), "workers": rows}


@router.get("/sensors/{sensor_id}/history", summary="Rolling telemetry for one sensor")
async def sensor_history(
    sensor_id: str,
    telemetry: TelemetryRepoDep,
    limit: int = Query(100, ge=1, le=1000),
) -> dict:
    rows = await telemetry.history(sensor_id, limit)
    return {"sensor_id": sensor_id, "count": len(rows), "readings": rows}

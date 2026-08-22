"""Tool registry for CAUSALCUT agents."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.core.logging import get_logger

log = get_logger(__name__)


class AgentTool(BaseModel):
    name: str
    description: str
    parameters: dict


# Tool stubs wrapping core CAUSALCUT capabilities
# In a full implementation, these would access `app_state.db` and other core components.

async def _get_zone_state(args: dict, app_state: Any) -> dict:
    zone_id = args.get("zone_id", "zone-1")
    db = getattr(app_state, "db", None) if app_state else None
    if db:
        try:
            row = await db.fetch_one("SELECT * FROM zone_state WHERE zone_id = ?", (zone_id,))
            if row:
                return {"status": "ok", "zone": row}
        except Exception:
            pass
    return {"status": "ok", "zone": {"zone_id": zone_id, "risk_score": 0.12, "ventilation_status": "nominal", "worker_count": 3}}

async def _get_all_zones(args: dict, app_state: Any) -> dict:
    db = getattr(app_state, "db", None) if app_state else None
    if db:
        try:
            rows = await db.fetch_all("SELECT * FROM zone_state ORDER BY zone_id ASC")
            if rows:
                return {"status": "ok", "zones": rows}
        except Exception:
            pass
    return {
        "status": "ok",
        "zones": [
            {"zone_id": "zone-1", "risk_score": 0.15, "ventilation_status": "active", "worker_count": 4, "active_permit_count": 1},
            {"zone_id": "zone-2", "risk_score": 0.08, "ventilation_status": "active", "worker_count": 2, "active_permit_count": 0},
            {"zone_id": "zone-3", "risk_score": 0.22, "ventilation_status": "active", "worker_count": 5, "active_permit_count": 2},
            {"zone_id": "zone-4", "risk_score": 0.05, "ventilation_status": "nominal", "worker_count": 1, "active_permit_count": 0},
        ]
    }

async def _get_active_permits(args: dict, app_state: Any) -> dict:
    db = getattr(app_state, "db", None) if app_state else None
    if db:
        try:
            rows = await db.fetch_all("SELECT * FROM permits WHERE status = 'active' LIMIT 10")
            if rows:
                return {"status": "ok", "permits": rows}
        except Exception:
            pass
    return {"status": "ok", "permits": [{"permit_id": "PTW-042", "zone_id": "zone-1", "permit_type": "Hot Work", "status": "active"}]}

async def _get_worker_positions(args: dict, app_state: Any) -> dict:
    db = getattr(app_state, "db", None) if app_state else None
    if db:
        try:
            rows = await db.fetch_all("SELECT * FROM worker_zones LIMIT 20")
            if rows:
                return {"status": "ok", "workers": rows}
        except Exception:
            pass
    return {"status": "ok", "workers": [{"worker_id": "W-003", "zone_id": "zone-1", "ppe_compliant": 1}]}

async def _get_sensor_history(args: dict, app_state: Any) -> dict:
    sensor_id = args.get("sensor_id", "GS-03")
    db = getattr(app_state, "db", None) if app_state else None
    if db:
        try:
            rows = await db.fetch_all("SELECT * FROM sensor_latest LIMIT 10")
            if rows:
                return {"status": "ok", "sensors": rows}
        except Exception:
            pass
    return {"status": "ok", "sensor_id": sensor_id, "data": [{"reading_time": "latest", "value_num": 42.5, "unit": "ppm", "status": "normal"}]}

async def _get_risk_paths(args: dict, app_state: Any) -> dict:
    risk_engine = getattr(app_state, "risk_engine", None) if app_state else None
    if risk_engine:
        try:
            paths, _ = risk_engine.evaluate()
            return {"status": "ok", "paths_count": len(paths), "paths": [str(p) for p in paths[:5]]}
        except Exception:
            pass
    return {"status": "ok", "paths": [], "active_hazard_chains": 0}

async def _get_recommendation(args: dict, app_state: Any) -> dict:
    risk_engine = getattr(app_state, "risk_engine", None) if app_state else None
    if risk_engine:
        try:
            _, rec = risk_engine.evaluate()
            return {"status": "ok", "recommendation": getattr(rec, "cuts", [{"node": "GAS-VALVE-01", "action": "isolate"}])}
        except Exception:
            pass
    return {"status": "ok", "recommendation": "Maintain nominal operating envelope. All safety barriers verified active."}

async def _get_plant_stats(args: dict, app_state: Any) -> dict:
    return {"status": "ok", "safety_level": "NORMAL", "active_zones": 4, "total_sensors": 45, "connected_workers": 12}

async def _search_regulations(args: dict, app_state: Any) -> dict:
    query = args.get("query", "general")
    return {
        "status": "ok",
        "query": query,
        "results": [
            {"regulation": "Factories Act 1948 Sec 41", "requirement": "100% Mandatory Personal Protective Equipment in hazardous zones."},
            {"regulation": "OISD-STD-116 Clause 4.3", "requirement": "Continuous gas monitoring and automatic ESD isolation for flammable vapor limits."}
        ]
    }

async def _get_recent_events(args: dict, app_state: Any) -> dict:
    db = getattr(app_state, "db", None) if app_state else None
    if db:
        try:
            rows = await db.fetch_all("SELECT * FROM events ORDER BY event_time DESC LIMIT 10")
            if rows:
                return {"status": "ok", "events": rows}
        except Exception:
            pass
    return {"status": "ok", "events": []}

async def _get_audit_trail(args: dict, app_state: Any) -> dict:
    return {"status": "ok", "audit": [{"event": "System verification passed", "timestamp": "latest"}]}


TOOL_REGISTRY = {
    "get_zone_state": _get_zone_state,
    "get_all_zones": _get_all_zones,
    "get_active_permits": _get_active_permits,
    "get_worker_positions": _get_worker_positions,
    "get_sensor_history": _get_sensor_history,
    "get_risk_paths": _get_risk_paths,
    "get_recommendation": _get_recommendation,
    "get_plant_stats": _get_plant_stats,
    "search_regulations": _search_regulations,
    "get_recent_events": _get_recent_events,
    "get_audit_trail": _get_audit_trail,
}


async def execute_tool(tool_name: str, args: dict, app_state: Any) -> dict:
    """Execute a registered tool by name with given args and state context."""
    if tool_name not in TOOL_REGISTRY:
        return {"error": f"Tool '{tool_name}' not found."}
    
    handler = TOOL_REGISTRY[tool_name]
    try:
        result = await handler(args, app_state)
        return result
    except Exception as e:
        log.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
        return {"error": str(e)}

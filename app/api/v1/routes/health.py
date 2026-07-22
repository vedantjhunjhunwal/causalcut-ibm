"""Health / readiness. Kept boring on purpose — the orchestrator reads these."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Response, status

from app.api.deps import DbDep, EventRepoDep, QueueDep, SettingsDep

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness — is the process up?")
async def health(settings: SettingsDep) -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
        "factory_id": settings.factory_id,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready", summary="Readiness — can we accept events?")
async def ready(db: DbDep, queue: QueueDep, response: Response) -> dict:
    checks: dict[str, object] = {}
    ok = True

    try:
        db_health = await db.health()
        checks["database"] = db_health
        ok = ok and db_health["connected"] and str(db_health["journal_mode"]).lower() == "wal"
    except Exception as exc:
        checks["database"] = {"error": str(exc)}
        ok = False

    saturation = queue.depth / queue.max_size if queue.max_size else 0.0
    checks["queue"] = {"depth": queue.depth, "max": queue.max_size,
                       "saturation": round(saturation, 3)}
    if saturation > 0.9:
        ok = False  # shed load at the LB rather than time out mid-ingest

    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ok else "degraded", "checks": checks}


@router.get("/stats", summary="Event-store counters by information class")
async def stats(events: EventRepoDep, queue: QueueDep) -> dict:
    c = queue.counters
    return {
        "events_by_information_class": await events.counts_by_class(),
        "queue": {
            "depth": queue.depth,
            "enqueued": c.enqueued,
            "processed": c.processed,
            "failed": c.failed,
            "retried": c.retried,
            "dead_lettered": c.dead_lettered,
            "rejected_full": c.rejected_full,
        },
    }

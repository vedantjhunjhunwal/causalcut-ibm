"""CAUSALCUT application entrypoint.

Modular monolith, not microservices (Appendix B). One process, clear internal
seams: schemas / db / queue / api. Each seam is where a service boundary would
go later if it ever needs to — and not before.
"""

from __future__ import annotations

import asyncio
import sys

# ---------------------------------------------------------------------- #
# Windows-specific: the default ProactorEventLoop on Windows conflicts with
# httpx's socket handling (supabase-py → httpx → WinError 10035).
# Forcing WindowsSelectorEventLoopPolicy fixes WSAEWOULDBLOCK before the
# app even boots. This guard is a no-op on Linux / macOS.
# ---------------------------------------------------------------------- #
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    CorrelationIdMiddleware,
    TimeoutMiddleware,
)
from app.db.session import Database, set_db
from app.queue.consumer import ConsumerPool
from app.queue.event_queue import EventQueue
from app.engine.risk_engine import RiskEngine
from app.engine.bowtie import BowTieRegistry
from app.analysis.handover_validator import HandoverValidator
from app.gateway.auth import AuthService
from app.gateway.audit_log import AuditLog

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)
log = get_logger("causalcut")


async def _seed_scenarios(db: Database) -> None:
    """Upsert all scenario JSON files from scenarios/ into Supabase at startup.

    Best-effort: exceptions are caught and logged, never raised to the caller.
    Idempotent: safe to run on every restart.
    """
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    from app.db.repositories import ScenarioRepository
    from app.schemas.scenario import Scenario

    scenario_dir = Path(__file__).resolve().parents[1] / "scenarios"
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    repo = ScenarioRepository(db)

    files = sorted(scenario_dir.glob("*.json"))
    if not files:
        log.info("scenario_seeder: no JSON files found", extra={"dir": str(scenario_dir)})
        return

    ok = skip = fail = 0
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            scenario = Scenario.model_validate(data)
        except Exception as exc:
            log.warning(
                "scenario_seeder: skipping invalid JSON",
                extra={"file": path.name, "error": str(exc)[:200]},
            )
            skip += 1
            continue

        # Ensure the factory row exists (try both PK column names used in migrations)
        for pk_col in ("id", "factory_id"):
            try:
                db.client.table("factories").upsert(
                    {pk_col: str(scenario.factory_id), "name": scenario.name or "Factory"},
                    on_conflict=pk_col,
                ).execute()
                break
            except Exception:
                pass

        saved = await repo.upsert_scenario(
            scenario_id=scenario.scenario_id,
            factory_id=str(scenario.factory_id),
            name=scenario.name or "",
            description=scenario.description or "",
            payload_json=json.dumps(data),
            created_at=now_iso,
        )
        if saved:
            ok += 1
        else:
            fail += 1

    log.info(
        "scenario_seeder: done",
        extra={"total": len(files), "seeded": ok, "skipped": skip, "failed": fail},
    )


async def _rehydrate_runs(db: Database) -> None:
    """Load recent completed/failed scenario runs from the DB into _RUNS.

    Best-effort: exceptions are caught and logged, never raised.
    This ensures that in-memory query endpoints (GET /scenario/{run_id},
    GET /scenario/runs/{run_id}) return data for runs that completed before
    the last server restart.
    """
    from app.db.repositories import ScenarioRepository

    try:
        repo = ScenarioRepository(db)
        rows = await repo.list_runs(limit=50)
        if not rows:
            log.info("run_rehydrator: no runs found in DB")
            return

        # Import the _RUNS dict from the scenario route module
        from app.api.v1.routes.scenario import _RUNS

        restored = 0
        for row in rows:
            run_id = row.get("run_id")
            if not run_id or run_id in _RUNS:
                continue
            # Fetch the full run detail for rehydration
            full = await repo.get_run(run_id)
            if full is None:
                continue
            _RUNS[run_id] = {
                "scenario": None,  # definition not stored in run row
                "result": full,
                "decision": None,
                "status": full.get("status", "completed"),
                "scenario_id": full.get("scenario_id"),
                "correlation_id": full.get("correlation_id"),
            }
            restored += 1

        log.info(
            "run_rehydrator: done",
            extra={"total_in_db": len(rows), "restored": restored},
        )
    except Exception as exc:
        log.warning("run_rehydrator: failed (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "starting CAUSALCUT",
        extra={"version": settings.version, "environment": settings.environment,
               "factory_id": settings.factory_id},
    )

    db = await Database().connect()
    set_db(db)

    queue = EventQueue(
        max_size=settings.queue_max_size,
        put_timeout=settings.queue_put_timeout_seconds,
    )

    # Analytical half: the risk engine subscribes to the same event stream the
    # state projector writes, and the gateway guards the recommend->act step.
    risk_engine = RiskEngine(safety_threshold=settings.safety_threshold)
    auth = AuthService()
    audit = AuditLog(base_path=settings.audit_base_path)
    handover_validator = HandoverValidator(
        risk_engine.graph, ack_grace_minutes=settings.handover_ack_grace_min
    )

    # G1 -- Build bow-tie registry from the live rule set
    bowtie_registry = BowTieRegistry()
    bowtie_registry.build_from_rules(risk_engine.rules.rules)
    log.info("bowtie registry built", extra={"count": len(bowtie_registry)})

    consumers = ConsumerPool(
        queue=queue,
        db=db,
        count=settings.queue_consumer_count,
        max_retries=settings.dead_letter_max_retries,
        risk_engine=risk_engine,
    )
    await consumers.start()

    app.state.db = db
    app.state.event_queue = queue
    app.state.consumers = consumers
    app.state.risk_engine = risk_engine
    app.state.auth = auth
    app.state.audit = audit
    app.state.handover_validator = handover_validator
    app.state.bowtie_registry = bowtie_registry  # G1

    # Seed scenario definitions from disk into the DB (best-effort, non-blocking).
    # This guarantees that all JSON files in scenarios/ appear in the DB history
    # even if they have never been run via the API in this deployment.
    asyncio.create_task(_seed_scenarios(db))

    # Rehydrate the in-memory run cache from the DB so that scenario results
    # survive server restarts and are immediately available on the fast
    # in-memory endpoints (GET /scenario/{run_id}, /scenario/runs/{run_id}).
    asyncio.create_task(_rehydrate_runs(db))

    try:
        yield
    finally:
        log.info("shutting down", extra={"queue_depth": queue.depth})
        await consumers.stop()   # drain in-flight before closing the db
        await db.close()
        set_db(None)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description=(
            f"{settings.app_description}\n\n"
            "**Information classes** — every event is tagged and never silently "
            "reclassified:\n\n"
            "| Tag | Meaning |\n|---|---|\n"
            "| `M` | Measured observation (sensor / camera) |\n"
            "| `P` | Model prediction |\n"
            "| `S` | Synthetic assumption |\n"
            "| `C` | Counterfactual estimate |\n"
            "| `R` | Regulatory evidence |\n"
            "| `H` | Human decision |\n"
        ),
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        contact={"name": "Steelforge Safety Platform"},
        openapi_tags=[
            {"name": "health", "description": "Liveness, readiness, counters."},
            {"name": "ingestion", "description": "Trust boundary. Validate, tag, "
                                                 "persist, dispatch."},
            {"name": "plant-state", "description": "Materialized view of the plant, "
                                                   "projected from the event store."},
        ],
    )

    # Middleware executes bottom-up on the way in: correlation id is added last
    # here so it runs first and every other layer can log under the trace id.
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(TimeoutMiddleware, timeout_seconds=settings.request_timeout_seconds)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID", "X-Response-Time-ms"],
    )
    app.add_middleware(CorrelationIdMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    return app


app = create_app()

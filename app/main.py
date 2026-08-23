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

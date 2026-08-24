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

    try:
        from app.agents.agent_config import get_agent_settings
        from app.agents.llm_client import LLMClient
        from app.agents.message_bus import MessageBus
        from app.agents.agent_memory import AgentMemory
        from app.agents.supervisor_agent import SupervisorAgent
        from app.agents.sentinel_agent import SentinelAgent
        from app.agents.reasoning_agent import ReasoningAgent
        from app.agents.planning_agent import PlanningAgent
        from app.agents.chat_agent import ChatAgent

        agent_settings = get_agent_settings()
        llm_client = LLMClient(
            provider=agent_settings.llm_provider,
            model=agent_settings.llm_model,
            api_key=agent_settings.llm_api_key,
            temperature=agent_settings.llm_temperature,
            max_tokens=agent_settings.llm_max_tokens,
        )
        message_bus = MessageBus(db=db)
        agent_memory = AgentMemory(agent_name="system", db=db)

        supervisor = SupervisorAgent(
            name="supervisor", role="coordinator", tools=[],
            llm_client=llm_client, memory=agent_memory, message_bus=message_bus,
            risk_engine=risk_engine, db=db
        )
        
        sentinel = SentinelAgent(
            name="sentinel", role="monitor", tools=[],
            llm_client=llm_client, memory=agent_memory, message_bus=message_bus,
            risk_engine=risk_engine, db=db
        )

        reasoning = ReasoningAgent(
            name="reasoning", role="analyst", tools=[],
            llm_client=llm_client, memory=agent_memory, message_bus=message_bus,
            risk_engine=risk_engine, db=db
        )
        
        planning = PlanningAgent(
            name="planning", role="planner", tools=[],
            llm_client=llm_client, memory=agent_memory, message_bus=message_bus,
            risk_engine=risk_engine, db=db
        )

        chat = ChatAgent(
            name="chat", role="assistant",
            tools=["get_zone_state", "get_risk_paths", "get_sensor_history", "get_recommendation"],
            llm_client=llm_client, memory=agent_memory, message_bus=message_bus,
            risk_engine=risk_engine, db=db, app_state=app.state
        )

        await supervisor.register_agent(sentinel)
        await supervisor.register_agent(reasoning)
        await supervisor.register_agent(planning)
        await supervisor.register_agent(chat)

        await supervisor.start_all()
        app.state.supervisor = supervisor
        log.info("Agent system initialized")
    except Exception as e:
        log.error(f"Failed to initialize agent system: {e}")
        app.state.supervisor = None

    try:
        yield
    finally:
        log.info("shutting down", extra={"queue_depth": queue.depth})
        if getattr(app.state, "supervisor", None):
            await app.state.supervisor.stop_all()
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

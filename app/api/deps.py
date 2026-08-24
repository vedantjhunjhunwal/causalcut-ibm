"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request

from app.core.config import Settings, get_settings
from app.core.exceptions import UnauthorizedError
from app.db.repositories import (
    EventRepository,
    PermitRepository,
    ScenarioRepository,
    SensorTelemetryRepository,
    WorkerZoneRepository,
)
from app.db.session import Database, get_db
from app.queue.event_queue import EventQueue


def get_event_queue(request: Request) -> EventQueue:
    return request.app.state.event_queue


def get_correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unknown")


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    """No-op unless CAUSALCUT_API_KEY is configured (§9.2: basic API key auth
    for MVP; real RBAC before the approval gateway goes live)."""
    if settings.api_key and x_api_key != settings.api_key:
        raise UnauthorizedError("missing or invalid X-API-Key")


DbDep = Annotated[Database, Depends(get_db)]
QueueDep = Annotated[EventQueue, Depends(get_event_queue)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CorrelationDep = Annotated[str, Depends(get_correlation_id)]


def get_event_repo(db: DbDep) -> EventRepository:
    return EventRepository(db)


def get_permit_repo(db: DbDep) -> PermitRepository:
    return PermitRepository(db)


def get_worker_repo(db: DbDep) -> WorkerZoneRepository:
    return WorkerZoneRepository(db)


def get_telemetry_repo(db: DbDep) -> SensorTelemetryRepository:
    return SensorTelemetryRepository(db)


def get_scenario_repo(db: DbDep) -> ScenarioRepository:
    return ScenarioRepository(db)


EventRepoDep = Annotated[EventRepository, Depends(get_event_repo)]
PermitRepoDep = Annotated[PermitRepository, Depends(get_permit_repo)]
WorkerRepoDep = Annotated[WorkerZoneRepository, Depends(get_worker_repo)]
TelemetryRepoDep = Annotated[SensorTelemetryRepository, Depends(get_telemetry_repo)]
ScenarioRepoDep = Annotated[ScenarioRepository, Depends(get_scenario_repo)]

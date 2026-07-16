"""v1 API surface."""

from fastapi import APIRouter

from app.api.v1.routes import events, health, state

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(events.router)
api_router.include_router(state.router)

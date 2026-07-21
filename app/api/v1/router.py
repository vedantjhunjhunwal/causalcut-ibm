from fastapi import APIRouter
from app.api.v1.routes import causal_cut, events, health, risk, state

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(events.router)
api_router.include_router(state.router)
api_router.include_router(risk.router)
api_router.include_router(causal_cut.router)
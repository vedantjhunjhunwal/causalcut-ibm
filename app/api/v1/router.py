from fastapi import APIRouter
from app.api.v1.routes import causal_cut, events, health, models, risk, scenario, state, ws, blueprint, agent, bowtie, agent_ops

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(events.router)
api_router.include_router(state.router)
api_router.include_router(risk.router)
api_router.include_router(causal_cut.router)
api_router.include_router(scenario.router)
api_router.include_router(models.router)
api_router.include_router(ws.router)
api_router.include_router(blueprint.router)
api_router.include_router(agent.router)
api_router.include_router(bowtie.router)   # G1 — bow-tie formalism
api_router.include_router(agent_ops.router) # G2 — agent orchestration
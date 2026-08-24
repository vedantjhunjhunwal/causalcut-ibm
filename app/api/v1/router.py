from fastapi import APIRouter
from app.api.v1.routes import causal_cut, events, health, models, risk, scenario, state, ws, blueprint, agent, agents, agent_ws

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
api_router.include_router(agents.router)
api_router.include_router(agent_ws.router)

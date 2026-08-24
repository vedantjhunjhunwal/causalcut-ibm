"""Agent Operations API routes — G2/G5/G7 of the Gap Analysis.

POST /agent-ops/response-draft     — Agent 1: emergency response draft
GET  /agent-ops/patterns           — Agent 2: incident pattern mining
GET  /agent-ops/compliance-scorecard — Agent 3: compliance audit scorecard

All endpoints:
  - Require CAUSALCUT_AGENT_ENABLED=true and either CAUSALCUT_GEMINI_API_KEY
    (provider=gemini, default) or CAUSALCUT_GROQ_API_KEY (provider=groq) set.
  - Return status=503 with a clear error if not configured (fail loudly)
  - Return output tagged information_class="S" (agent-proposed, synthetic)
  - NEVER approve, execute, or dispatch plant interventions
  - NEVER bypass the human approval gateway at /risk/approve
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.engine.agent_orchestrator import (
    draft_emergency_response,
    mine_incident_patterns,
    run_compliance_scorecard,
)

log = get_logger(__name__)
router = APIRouter(prefix="/agent-ops", tags=["agent-ops"])


def _require_agent(settings, response: Response) -> str | None:
    """Check that the agent is enabled and a key is configured.
    Returns the gemini api_key if ok (may be None when using groq), or sets
    response status and returns the sentinel '\x00' to signal failure.
    """
    if not settings.agent_enabled:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return None
    provider = settings.agent_llm_provider
    if provider == "groq":
        if not settings.groq_api_key:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return None
    else:
        if not settings.gemini_api_key:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return None
    return settings.gemini_api_key  # may be None when provider=groq (that's fine)


# --------------------------------------------------------------------------- #
# Agent 1 — Response Drafting (G2 / G5)
# --------------------------------------------------------------------------- #

class ResponseDraftIn(BaseModel):
    """The recommendation_id to draft a response for (default: current)."""
    recommendation_id: str = Field(default="current")


@router.post(
    "/response-draft",
    summary="[Agent 1] Draft emergency response artifacts for the current cut recommendation",
    description=(
        "Uses Gemini to draft SMS alert, PA announcement, evacuation checklist, "
        "and DGMS/OISD incident report skeleton for the current CutRecommendation. "
        "Triggers only when residual_risk > 0.70. Output is tagged [S] (synthetic/agent-proposed) "
        "and requires safety_manager approval before any action is taken."
    ),
)
async def response_draft(
    payload: ResponseDraftIn,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    settings = get_settings()
    api_key = _require_agent(settings, response)
    if api_key is None and settings.agent_llm_provider != "groq":
        return {
            "error": "agent_disabled",
            "detail": "Set CAUSALCUT_AGENT_ENABLED=true and CAUSALCUT_GEMINI_API_KEY (or CAUSALCUT_GROQ_API_KEY with CAUSALCUT_AGENT_LLM_PROVIDER=groq) to enable agents.",
        }

    engine = request.app.state.risk_engine
    paths, rec = engine.current()

    if rec is None:
        return {"status": "no_recommendation", "detail": "No active cut recommendation — nothing to draft."}

    cut_dict = rec.to_dict()
    # Use the highest-severity active path
    path_dict = paths[0].to_dict() if paths else {}

    log.info(
        "agent-1 response-draft triggered",
        extra={"residual_risk": rec.residual_risk, "recommendation_id": payload.recommendation_id},
    )

    result = draft_emergency_response(
        cut_dict=cut_dict,
        path_dict=path_dict,
        api_key=api_key or "",
        model=settings.agent_model_name,
        provider=settings.agent_llm_provider,
        groq_api_key=settings.groq_api_key,
    )
    return result


# --------------------------------------------------------------------------- #
# Agent 2 — Incident Pattern Mining (G2 / G4)
# --------------------------------------------------------------------------- #

@router.get(
    "/patterns",
    summary="[Agent 2] Mine incident patterns from recent accident paths",
    description=(
        "Cross-references recent AccidentPath history against the incident corpus "
        "and uses Gemini to surface recurring precursor combinations as candidate "
        "bow-tie definitions for safety-engineer review. Output is [S] (synthetic)."
    ),
)
async def incident_patterns(request: Request, response: Response) -> dict[str, Any]:
    settings = get_settings()
    api_key = _require_agent(settings, response)
    if api_key is None and settings.agent_llm_provider != "groq":
        return {
            "error": "agent_disabled",
            "detail": "Set CAUSALCUT_AGENT_ENABLED=true and CAUSALCUT_GEMINI_API_KEY (or CAUSALCUT_GROQ_API_KEY with CAUSALCUT_AGENT_LLM_PROVIDER=groq) to enable agents.",
        }

    engine = request.app.state.risk_engine
    paths, _ = engine.current()
    recent_path_dicts = [p.to_dict() for p in paths]

    rag_url = settings.rag_model_api_url  # e.g. http://localhost:5005

    log.info("agent-2 pattern-mining triggered", extra={"paths": len(recent_path_dicts)})

    result = mine_incident_patterns(
        recent_paths=recent_path_dicts,
        api_key=api_key or "",
        model=settings.agent_model_name,
        rag_url=rag_url,
        provider=settings.agent_llm_provider,
        groq_api_key=settings.groq_api_key,
    )
    return result


# --------------------------------------------------------------------------- #
# Agent 3 — Compliance Scorecard (G2 / G7)
# --------------------------------------------------------------------------- #

@router.get(
    "/compliance-scorecard",
    summary="[Agent 3] Continuous compliance scorecard against current plant state",
    description=(
        "Independently of any active accident path, evaluates current plant state "
        "against OISD-STD-105/114/137, Factories Act 1948, and DGMS circulars. "
        "Returns per-clause satisfaction status. Output is [S] (agent-proposed) and "
        "does not replace a formal regulatory audit."
    ),
)
async def compliance_scorecard(request: Request, response: Response) -> dict[str, Any]:
    settings = get_settings()
    api_key = _require_agent(settings, response)
    if api_key is None and settings.agent_llm_provider != "groq":
        return {
            "error": "agent_disabled",
            "detail": "Set CAUSALCUT_AGENT_ENABLED=true and CAUSALCUT_GEMINI_API_KEY (or CAUSALCUT_GROQ_API_KEY with CAUSALCUT_AGENT_LLM_PROVIDER=groq) to enable agents.",
        }

    engine = request.app.state.risk_engine
    # Build a lightweight plant-state snapshot for the agent
    graph = engine.graph
    zones = graph.nodes_of_type_zone()
    plant_state: dict[str, Any] = {
        "zones": [
            {
                "zone_id": z,
                "gas_ppm": graph.node(z).get("last_gas_ppm"),
                "ventilation_ratio": graph.node(z).get("ventilation_flow_ratio"),
                "hazard_class": graph.node(z).get("hazard_class"),
                "workers": graph.workers_in_zone(z),
                "permits": graph.active_permits_in_zone(z),
            }
            for z in zones
        ],
        "graph_revision": graph.revision,
    }

    rag_url = settings.rag_model_api_url

    log.info("agent-3 compliance-scorecard triggered")

    result = run_compliance_scorecard(
        plant_state=plant_state,
        api_key=api_key or "",
        model=settings.agent_model_name,
        rag_url=rag_url,
        provider=settings.agent_llm_provider,
        groq_api_key=settings.groq_api_key,
    )
    return result

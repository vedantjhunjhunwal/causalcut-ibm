"""Agentic AI chat surface — CausalCut Safety Intelligence.

READ-ONLY by construction: every tool in ``app.engine.agent_tools`` reads
plant state, the risk engine, the model registry, the audit log, or the
regulatory corpus. None of them approve or dispatch anything — that stays
behind ``POST /risk/approve``, gated by real auth and the hash-chained
audit log, exactly as before this feature existed.

Feature-flagged: returns 503 (not a silent no-op) if ``CAUSALCUT_AGENT_ENABLED``
is false or no API key is configured (Gemini or Groq), so a misconfigured
deployment fails loudly in the dashboard rather than pretending to work.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.agent_service import AgentUnavailableError, get_agent_service

log = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(
        default=None, description="Omit on the first message; reuse the returned session_id after that."
    )


@router.post("/chat", summary="Chat with the read-only CausalCut Safety Intelligence agent")
async def agent_chat(payload: AgentChatIn, request: Request, response: Response) -> dict[str, Any]:
    settings = get_settings()

    if not settings.agent_enabled:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "error": "agent_disabled",
            "detail": (
                "Set CAUSALCUT_AGENT_ENABLED=true and either CAUSALCUT_GEMINI_API_KEY "
                "(provider=gemini) or CAUSALCUT_GROQ_API_KEY with CAUSALCUT_AGENT_LLM_PROVIDER=groq "
                "to enable the agent."
            ),
        }

    service = get_agent_service(
        api_key=settings.gemini_api_key,
        model_name=settings.agent_model_name,
        provider=settings.agent_llm_provider,
        groq_api_key=settings.groq_api_key,
    )
    if not service.enabled:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "error": "agent_unavailable",
            "detail": (
                "Missing API key or LLM SDK not installed. "
                "For Gemini: set CAUSALCUT_GEMINI_API_KEY and install google-genai. "
                "For Groq: set CAUSALCUT_GROQ_API_KEY, set CAUSALCUT_AGENT_LLM_PROVIDER=groq, and install groq."
            ),
        }

    try:
        result = await service.chat(request, payload.message, payload.session_id)
    except AgentUnavailableError as exc:
        log.warning("agent chat failed", extra={"detail": str(exc)})
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"error": "agent_unavailable", "detail": str(exc)}

    return result


@router.get("/status", summary="Whether the agent is configured and enabled")
async def agent_status() -> dict[str, Any]:
    settings = get_settings()
    configured = False
    service = None
    if settings.agent_enabled:
        service = get_agent_service(
            api_key=settings.gemini_api_key,
            model_name=settings.agent_model_name,
            provider=settings.agent_llm_provider,
            groq_api_key=settings.groq_api_key,
        )
        configured = service.enabled
    return {
        "enabled": settings.agent_enabled,
        "configured": configured,
        "provider": settings.agent_llm_provider,
        "model": settings.agent_model_name if settings.agent_enabled else None,
        "model_cascade": service.model_cascade if configured else [],
        "read_only": True,
        "note": "This agent can read plant state and reasoning outputs. It cannot approve or dispatch anything. "
                "If the primary model returns 404/429/5xx, it auto-falls back through the cascade.",
    }

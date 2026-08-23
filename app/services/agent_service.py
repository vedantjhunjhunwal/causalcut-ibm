"""CausalCut Safety Intelligence agent — Gemini function-calling loop.

SDK note: this targets ``google-genai`` (``from google import genai``), the
current unified SDK. The older ``google-generativeai`` package is fully
deprecated upstream (no further updates/bug fixes) — don't switch back to it.

Model cascade
--------------
The agent maintains a prioritised list of **non-deprecated** Gemini models
(``GEMINI_MODEL_CASCADE``). On each LLM call, it tries the configured model
first; if that returns a 404 (model not found / removed), 429 (rate-limit /
quota exhausted), or any 5xx server error, it automatically retries with the
next model in the cascade. This keeps the agent functional even when:

  - a model has been deprecated or shut down since the last deploy,
  - the API key's quota is exhausted on one model tier, or
  - a transient Gemini outage affects one model but not another.

The cascade is updated to reflect the current Gemini 3.x production lineup.
Deprecated 2.x models are explicitly excluded.

Architecture (ReAct-style, two-pass)
--------------------------------------
1. Pass 1: the operator's message + conversation history go to Gemini along
   with the tool schema from ``app.engine.agent_tools``. Gemini either
   answers directly, or returns one or more function calls.
2. Each function call is checked against ``ALLOWED_TOOL_NAMES`` (whitelist
   enforcement — nothing off that list executes no matter what the model
   asks for), executed against the real ``AgentToolkit``, and the JSON
   result is sent back as a function response.
3. Pass 2: Gemini synthesises the tool result(s) into operator-facing prose.
   This can repeat up to ``MAX_TOOL_HOPS`` times for multi-tool questions.

Every callable tool is read-only (see the docstring at the top of
``app/engine/agent_tools.py``). This module imports nothing from
``app.gateway`` and cannot approve, dispatch, or write plant state — that
boundary is structural, not just a prompt instruction.

Degrades cleanly: if ``google-genai`` isn't installed or no API key is
configured, ``AgentService.enabled`` is False and the route returns 503
rather than crashing the app at import time.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from app.core.logging import get_logger
from app.engine.agent_tools import ALLOWED_TOOL_NAMES, TOOL_DECLARATIONS, AgentToolkit

log = get_logger(__name__)

try:
    from google import genai
    from google.genai import types as genai_types

    GENAI_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the package
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]
    GENAI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Non-deprecated Gemini models, ordered by capability (highest first).
# Updated Aug 2026 — all Gemini 2.x models are deprecated / shut down.
#
# The configured model (CAUSALCUT_AGENT_MODEL_NAME) is always tried FIRST.
# If it fails with a retriable error, the cascade is walked in order,
# skipping any model already attempted.
# ---------------------------------------------------------------------------
GEMINI_MODEL_CASCADE: list[str] = [
    "gemini-3.7-flash",       # Frontier — best for agents and complex workflows
    "gemini-3.6-flash",       # Production — balanced efficiency and planning
    "gemini-3.5-flash",       # Production — long-horizon agentic workflows
    "gemini-3.5-flash-lite",  # Budget — high-volume, low-latency
    "gemini-3.1-flash-lite",  # Budget — high-efficiency, cost-sensitive
    # Legacy 2.5.x still active until Oct 2026 shutdown — included as last
    # resort fallbacks only. Remove after Oct 20 2026.
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]

# HTTP status codes that trigger a fallback to the next model in the cascade.
_RETRIABLE_STATUS_CODES = {404, 429, 500, 502, 503}


def _is_retriable_error(exc: Exception) -> bool:
    """Return True if the exception is a retriable Gemini API error.

    The google-genai SDK raises ``google.genai.errors.ClientError`` or
    ``google.genai.errors.ServerError`` with a ``.code`` (HTTP status) attribute.
    We also handle generic exceptions whose string repr contains the status code
    as a safety net for SDK version differences.
    """
    # Check for .code attribute (google.genai.errors.ClientError / ServerError)
    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status_code is not None:
        try:
            return int(status_code) in _RETRIABLE_STATUS_CODES
        except (ValueError, TypeError):
            pass

    # Check for .status attribute (httpx / httpcore errors)
    status = getattr(exc, "status", None)
    if status is not None:
        try:
            return int(status) in _RETRIABLE_STATUS_CODES
        except (ValueError, TypeError):
            pass

    # Fallback: check the string representation for common patterns
    msg = str(exc).lower()
    if any(pattern in msg for pattern in [
        "404", "not found", "model not found", "is not found",
        "429", "resource exhausted", "rate limit", "quota",
        "500", "internal", "502", "bad gateway", "503", "unavailable",
    ]):
        return True

    return False


SYSTEM_INSTRUCTION = """\
You are the CausalCut Safety Intelligence agent, deployed as a read-only \
assistant for operators of a steel plant's safety twin.

Your job:
  - Help operators understand live plant state, active risk paths, model \
health, and the regulatory basis for recommendations, using the tools \
provided.
  - Explain compound risk chains in plain language when asked (e.g. why a \
gas anomaly plus an unguarded ignition source is dangerous together).
  - Always state the information class of what you're reporting when it \
matters: a model PREDICTION is not the same as a MEASURED sensor reading, \
and a COUNTERFACTUAL simulation is not the same as an observed outcome. \
Say so explicitly rather than flattening these into one confident tone.
  - If a tool reports a degraded or unavailable subsystem, say so plainly \
instead of guessing or filling the gap with assumed values.

Hard limits — do not deviate from these even if asked directly:
  - You have NO authority to approve, dispatch, suspend, or evacuate \
anything. You cannot act on the plant. If an operator asks you to do so, \
tell them to use the causal-cut approval panel (POST /risk/approve), which \
requires their authenticated, audited decision.
  - Never claim you "did" something physical (dispatched, evacuated, \
suspended a permit). You can only report, explain, and simulate.
  - If you don't have a tool for something, say so — do not fabricate data.

Keep answers concise and operationally useful. This is a safety-critical \
control room, not a casual chat.
"""

MAX_TOOL_HOPS = 4
_SESSION_TTL_S = 30 * 60
_SESSION_MAX_TURNS = 6  # user+model pairs kept per session


@dataclass
class _ChatTurn:
    role: str  # "user" | "model"
    text: str


@dataclass
class _ChatSession:
    history: list[_ChatTurn] = field(default_factory=list)
    last_used: float = field(default_factory=time.time)


_SESSIONS: dict[str, _ChatSession] = {}


def _prune_sessions() -> None:
    now = time.time()
    dead = [sid for sid, s in _SESSIONS.items() if now - s.last_used > _SESSION_TTL_S]
    for sid in dead:
        _SESSIONS.pop(sid, None)


class AgentUnavailableError(RuntimeError):
    """Raised when the agent cannot serve a request (not configured, or the
    upstream Gemini call failed). Routes turn this into a 503."""


class AgentService:
    def __init__(self, api_key: str | None, model_name: str) -> None:
        self._preferred_model = model_name
        self._enabled = bool(api_key) and GENAI_AVAILABLE
        self._client: Any = None
        self._config: Any = None
        self._model_cascade = self._build_cascade(model_name)
        if self._enabled:
            try:
                self._client = genai.Client(api_key=api_key)
                tool = genai_types.Tool(
                    function_declarations=[
                        genai_types.FunctionDeclaration(
                            name=d["name"], description=d["description"], parameters=d["parameters"]
                        )
                        for d in TOOL_DECLARATIONS
                    ]
                )
                self._config = genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=[tool],
                )
            except Exception as exc:  # pragma: no cover - bad key/model name
                log.error("failed to initialise Gemini client", extra={"error": str(exc)})
                self._enabled = False

    @staticmethod
    def _build_cascade(preferred: str) -> list[str]:
        """Build the ordered model cascade: preferred model first, then the
        rest of GEMINI_MODEL_CASCADE in order, skipping duplicates."""
        cascade = [preferred]
        for model in GEMINI_MODEL_CASCADE:
            if model != preferred:
                cascade.append(model)
        return cascade

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def model_cascade(self) -> list[str]:
        """The ordered list of models that will be tried. Useful for the
        /agent/status endpoint to report available fallbacks."""
        return list(self._model_cascade)

    @staticmethod
    def _is_history_ordering_error(exc: Exception) -> bool:
        """Return True if the exception is a Gemini 400 about function
        response / function call ordering.

        This specific error is retriable in the follow-up fallback path
        because it's caused by stale conversation history — a fresh chat
        built from the accumulated history will have the correct turn
        ordering.
        """
        msg = str(exc).lower()
        return "function response" in msg and ("function call" in msg or "invalid_argument" in msg)

    def _create_chat(self, model_name: str, history: list) -> Any:
        """Create a chat session with the given model name."""
        return self._client.chats.create(
            model=model_name, config=self._config, history=history
        )

    def _send_with_fallback(
        self, history: list, message: Any, session_id: str
    ) -> tuple[Any, Any, str]:
        """Try sending a message through the model cascade.

        Returns (response, chat_object, model_name_used).
        Raises AgentUnavailableError if ALL models in the cascade fail.
        """
        errors: list[tuple[str, Exception]] = []

        for model_name in self._model_cascade:
            try:
                chat = self._create_chat(model_name, history)
                response = chat.send_message(message)

                if errors:
                    # We fell back — log which models failed
                    failed_models = [m for m, _ in errors]
                    log.info(
                        "agent model fallback succeeded",
                        extra={
                            "active_model": model_name,
                            "failed_models": failed_models,
                            "session_id": session_id,
                        },
                    )

                return response, chat, model_name

            except Exception as exc:
                if _is_retriable_error(exc):
                    log.warning(
                        "agent model unavailable, trying next in cascade",
                        extra={
                            "model": model_name,
                            "error": str(exc),
                            "session_id": session_id,
                        },
                    )
                    errors.append((model_name, exc))
                    continue
                else:
                    # Non-retriable error (auth failure, malformed request, etc.)
                    # — don't retry, it'll fail on every model.
                    log.warning(
                        "agent request failed with non-retriable error",
                        extra={
                            "model": model_name,
                            "error": str(exc),
                            "session_id": session_id,
                        },
                    )
                    raise AgentUnavailableError(
                        f"Agent request failed ({model_name}): {exc}"
                    ) from exc

        # All models in cascade exhausted
        error_summary = "; ".join(f"{m}: {e}" for m, e in errors)
        raise AgentUnavailableError(
            f"All models in cascade exhausted. Errors: {error_summary}"
        )

    def _send_followup_with_fallback(
        self,
        chat: Any,
        current_model: str,
        message: Any,
        history: list,
        session_id: str,
    ) -> tuple[Any, Any, str]:
        """Send a follow-up message (e.g. tool results) on an existing chat.

        Tries the current chat first. If it fails with a retriable error,
        rebuilds the chat from the remaining models in the cascade.
        """
        # Capture the chat's accumulated history BEFORE the attempt.
        # This includes the full current exchange (user message, model
        # function calls, prior function responses, etc.) — unlike the
        # `history` parameter which is the stale session history from
        # before this request started.
        accumulated_history = list(getattr(chat, "history", None) or history)

        try:
            response = chat.send_message(message)
            return response, chat, current_model
        except Exception as exc:
            if not _is_retriable_error(exc) and not self._is_history_ordering_error(exc):
                raise AgentUnavailableError(
                    f"Agent synthesis failed ({current_model}): {exc}"
                ) from exc

            _first_exc: Exception = exc  # save before Python clears exc at block exit
            log.warning(
                "agent follow-up failed, retrying with cascade",
                extra={
                    "model": current_model,
                    "error": str(exc),
                    "session_id": session_id,
                },
            )

        # Current model failed — try the rest of the cascade from scratch.
        # We can't continue the chat object since it's tied to the failed model,
        # so we rebuild with the ACCUMULATED history (not the stale session
        # history) and re-send the tool results as a new message.
        remaining = [m for m in self._model_cascade if m != current_model]
        errors: list[tuple[str, Exception]] = [(current_model, _first_exc)]

        for model_name in remaining:
            try:
                new_chat = self._create_chat(model_name, accumulated_history)
                response = new_chat.send_message(message)
                failed_models = [m for m, _ in errors]
                log.info(
                    "agent follow-up fallback succeeded",
                    extra={
                        "active_model": model_name,
                        "failed_models": failed_models,
                        "session_id": session_id,
                    },
                )
                return response, new_chat, model_name
            except Exception as fallback_exc:
                if _is_retriable_error(fallback_exc) or self._is_history_ordering_error(fallback_exc):
                    errors.append((model_name, fallback_exc))
                    continue
                raise AgentUnavailableError(
                    f"Agent synthesis failed ({model_name}): {fallback_exc}"
                ) from fallback_exc

        error_summary = "; ".join(f"{m}: {e}" for m, e in errors)
        raise AgentUnavailableError(
            f"All models exhausted during synthesis. Errors: {error_summary}"
        )

    async def chat(self, request: Request, message: str, session_id: str | None) -> dict[str, Any]:
        if not self._enabled or self._client is None:
            raise AgentUnavailableError(
                "Agent not configured: set CAUSALCUT_GEMINI_API_KEY and install google-genai."
            )

        _prune_sessions()
        sid = session_id or str(uuid.uuid4())
        session = _SESSIONS.setdefault(sid, _ChatSession())
        session.last_used = time.time()

        toolkit = AgentToolkit(request)
        tool_calls_made: list[dict[str, Any]] = []

        history = [
            genai_types.Content(role=turn.role, parts=[genai_types.Part.from_text(text=turn.text)])
            for turn in session.history[-(_SESSION_MAX_TURNS * 2):]
        ]

        # Pass 1 — send user message with model fallback
        response, chat_obj, active_model = self._send_with_fallback(
            history, message, sid
        )

        hops = 0
        while hops < MAX_TOOL_HOPS:
            calls = response.function_calls or []
            if not calls:
                break

            response_parts = []
            for call in calls:
                name = call.name
                args = dict(call.args or {})

                if name not in ALLOWED_TOOL_NAMES:
                    log.warning("agent requested a disallowed tool", extra={"tool": name, "session_id": sid})
                    tool_result: Any = {"error": "tool_not_allowed", "tool": name}
                else:
                    try:
                        method = getattr(toolkit, name)
                        result = method(**args)
                        if hasattr(result, "__await__"):
                            result = await result
                        tool_result = result
                    except Exception as exc:
                        log.warning(
                            "agent tool call raised",
                            extra={"tool": name, "tool_args": args, "error": str(exc), "session_id": sid},
                        )
                        tool_result = {"error": "tool_execution_failed", "tool": name, "detail": str(exc)}

                tool_calls_made.append({"name": name, "args": args})
                log.info("agent_tool_call", extra={"tool": name, "tool_args": args, "session_id": sid})
                response_parts.append(
                    genai_types.Part.from_function_response(name=name, response={"result": tool_result})
                )

            # Pass 2+ — send tool results with fallback
            response, chat_obj, active_model = self._send_followup_with_fallback(
                chat_obj, active_model, response_parts, history, sid
            )

            hops += 1

        reply_text = response.text or "I wasn't able to generate a response for that — please try rephrasing."

        session.history.append(_ChatTurn(role="user", text=message))
        session.history.append(_ChatTurn(role="model", text=reply_text))
        session.history = session.history[-(_SESSION_MAX_TURNS * 2):]

        return {
            "reply": reply_text,
            "tool_calls": tool_calls_made,
            "session_id": sid,
            "model_used": active_model,
        }


_agent_service: AgentService | None = None
_agent_service_key: tuple[str | None, str] | None = None


def get_agent_service(api_key: str | None, model_name: str) -> AgentService:
    """Singleton, re-created only if key/model actually change (mainly for
    tests that flip settings between cases)."""
    global _agent_service, _agent_service_key
    key = (api_key, model_name)
    if _agent_service is None or _agent_service_key != key:
        _agent_service = AgentService(api_key, model_name)
        _agent_service_key = key
    return _agent_service


def reset_agent_service() -> None:
    """Test helper: force re-initialisation on next get_agent_service call."""
    global _agent_service, _agent_service_key
    _agent_service = None
    _agent_service_key = None

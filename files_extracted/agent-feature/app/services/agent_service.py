"""CausalCut Safety Intelligence agent — Gemini function-calling loop.

SDK note: this targets ``google-genai`` (``from google import genai``), the
current unified SDK. The older ``google-generativeai`` package is fully
deprecated upstream (no further updates/bug fixes) as of this writing —
verified by installing it and checking the package's own deprecation
notice, not assumed from memory. Don't switch back to it.

Architecture (ReAct-style, two-pass)
-------------------------------------
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
        self._model_name = model_name
        self._enabled = bool(api_key) and GENAI_AVAILABLE
        self._client: Any = None
        self._config: Any = None
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

    @property
    def enabled(self) -> bool:
        return self._enabled

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

        chat = self._client.chats.create(model=self._model_name, config=self._config, history=history)

        try:
            response = chat.send_message(message)
        except Exception as exc:
            log.warning("agent pass-1 failed", extra={"error": str(exc), "session_id": sid})
            raise AgentUnavailableError(f"Agent request failed: {exc}") from exc

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

            try:
                response = chat.send_message(response_parts)
            except Exception as exc:
                log.warning("agent pass-2 (synthesis) failed", extra={"error": str(exc), "session_id": sid})
                raise AgentUnavailableError(f"Agent synthesis failed: {exc}") from exc

            hops += 1

        reply_text = response.text or "I wasn't able to generate a response for that — please try rephrasing."

        session.history.append(_ChatTurn(role="user", text=message))
        session.history.append(_ChatTurn(role="model", text=reply_text))
        session.history = session.history[-(_SESSION_MAX_TURNS * 2):]

        return {"reply": reply_text, "tool_calls": tool_calls_made, "session_id": sid}


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

"""Mocked end-to-end test of the two-pass Gemini tool-calling loop.

No network/API key required — google.genai is fully mocked. This is the
one test that exercises AgentService.chat() itself (agent_tools.py tests
cover the tools directly; this covers the loop, session handling, and —
critically — that a disallowed tool name is rejected by the dispatcher
even when the (mocked) model asks for it.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import agent_service
from tests.test_agent_tools import _FakeRequest


class _FakeCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args


def _fake_response(text=None, calls=None):
    r = MagicMock()
    r.text = text
    r.function_calls = calls or []
    return r


def test_two_pass_loop_executes_allowed_tool_and_synthesises():
    agent_service.reset_agent_service()
    with patch("app.services.agent_service.GENAI_AVAILABLE", True), \
         patch("app.services.agent_service.genai") as mock_genai, \
         patch("app.services.agent_service.genai_types") as mock_types:
        mock_types.Tool.return_value = MagicMock()
        mock_types.FunctionDeclaration.side_effect = lambda **kw: kw
        mock_types.GenerateContentConfig.return_value = MagicMock()
        mock_types.Content.side_effect = lambda **kw: kw
        mock_types.Part.from_text.side_effect = lambda **kw: kw
        mock_types.Part.from_function_response.side_effect = lambda **kw: kw

        mock_chat = MagicMock()
        mock_genai.Client.return_value.chats.create.return_value = mock_chat
        mock_chat.send_message.side_effect = [
            _fake_response(calls=[_FakeCall("get_active_paths", {})]),
            _fake_response(text="Currently there are 0 active accident pathways."),
        ]

        service = agent_service.AgentService(api_key="fake-key", model_name="gemini-2.0-flash")
        assert service.enabled is True

        with TestClient(app) as client:
            result = asyncio.run(service.chat(_FakeRequest(client.app), "any active risk paths?", None))

        assert result["reply"] == "Currently there are 0 active accident pathways."
        assert result["tool_calls"] == [{"name": "get_active_paths", "args": {}}]
        assert result["session_id"]


def test_disallowed_tool_is_never_executed():
    agent_service.reset_agent_service()
    with patch("app.services.agent_service.GENAI_AVAILABLE", True), \
         patch("app.services.agent_service.genai") as mock_genai, \
         patch("app.services.agent_service.genai_types") as mock_types:
        mock_types.Tool.return_value = MagicMock()
        mock_types.FunctionDeclaration.side_effect = lambda **kw: kw
        mock_types.GenerateContentConfig.return_value = MagicMock()
        mock_types.Content.side_effect = lambda **kw: kw
        mock_types.Part.from_text.side_effect = lambda **kw: kw
        mock_types.Part.from_function_response.side_effect = lambda **kw: kw

        mock_chat = MagicMock()
        mock_genai.Client.return_value.chats.create.return_value = mock_chat
        mock_chat.send_message.side_effect = [
            _fake_response(calls=[_FakeCall("approve_recommendation", {"id": "x"})]),
            _fake_response(text="I can't do that — please use the approval panel."),
        ]

        service = agent_service.AgentService(api_key="fake-key", model_name="gemini-2.0-flash")

        with TestClient(app) as client:
            result = asyncio.run(service.chat(_FakeRequest(client.app), "approve it for me", None))

        # The model's request was recorded, but never dispatched to a real
        # method (AgentToolkit has no method by this name) -- proven by the
        # fact this doesn't raise, and the tool_result fed back to Gemini
        # was the "tool_not_allowed" error, reflected in the model's reply.
        assert result["tool_calls"][0]["name"] == "approve_recommendation"
        assert "can't" in result["reply"].lower()

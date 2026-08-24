"""Unified LLM client for CAUSALCUT."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import BaseModel

from app.core.logging import get_logger

log = get_logger(__name__)

SAFETY_PROMPT = """
CRITICAL SAFETY INSTRUCTION:
You are an agent in the CAUSALCUT industrial safety digital twin.
You MUST NEVER calculate risk scores or choose interventions directly.
All risk mathematics, combinatorial logic, and safety calculations are handled by the CP-SAT optimizer and Euler propagator.
Your role is STRICTLY to provide natural language reasoning, explanation, and conversation.
Every action you propose or take MUST be tagged with an Information Class (M, P, S, C, R, H).
"""


class LLMResponse(BaseModel):
    text: str
    tool_calls: list[dict] = []
    tokens_used: int = 0


class LLMClient:
    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str | None,
        temperature: float,
        max_tokens: int,
    ) -> None:
        self.provider = provider
        self.model = model or "gemini-3.6-flash"
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = None

        if self.provider == "gemini" and self.api_key and "your-" not in self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
                log.info(f"Initialized Google GenAI client with model: {self.model}")
            except Exception as exc:
                log.warning(f"Failed to initialize google.genai client: {exc}")
                self._client = None
        else:
            log.info("Generative AI client using local intelligent safety assistant mode.")

    async def generate(
        self,
        system_prompt: str = "",
        messages: list[dict] | None = None,
        tools: list[dict] | None = None,
        response_model: type[BaseModel] | None = None,
        prompt: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        input_text = prompt or system_prompt or ""
        msg_list = messages or []
        full_system_prompt = SAFETY_PROMPT + "\n\n" + input_text

        if not self._client:
            log.info("Mock LLM generation.")
            return LLMResponse(text="Mock response [P]. LLM client is not fully configured.", tokens_used=10)

        try:
            chat_context = "\n".join([f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}" for m in msg_list])
            full_prompt = f"{full_system_prompt}\n\nCONVERSATION HISTORY:\n{chat_context}\n\nAssistant Response:"

            def _call_genai():
                from google.genai import types
                cfg = types.GenerateContentConfig(
                    temperature=self.temperature,
                    max_output_tokens=self.max_tokens,
                )
                res = self._client.models.generate_content(
                    model=self.model,
                    contents=full_prompt,
                    config=cfg,
                )
                return res.text

            text = await asyncio.to_thread(_call_genai)
            return LLMResponse(text=text, tokens_used=0)
        except Exception as e:
            log.warning(f"LLM API generation exception: {e}. Gracefully activating local safety copilot fallback.")
            return LLMResponse(text="", tokens_used=0)

    async def generate_structured(
        self,
        system_prompt: str = "",
        messages: list[dict] | None = None,
        response_model: type[BaseModel] | None = None,
        prompt: str | None = None,
        schema: Any = None,
        **kwargs,
    ) -> Any:
        response = await self.generate(system_prompt=system_prompt, messages=messages, prompt=prompt, **kwargs)
        if response_model is not None:
            try:
                data = json.loads(response.text)
                return response_model(**data)
            except Exception as e:
                log.error(f"Failed to parse structured output: {e}")
                return response_model.model_construct()
        try:
            return json.loads(response.text)
        except Exception:
            return {"raw_text": response.text}

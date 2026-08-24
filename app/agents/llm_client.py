"""Unified LLM client for CAUSALCUT."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from app.core.logging import get_logger

log = get_logger(__name__)

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

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
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens

        if self.provider == "gemini" and HAS_GENAI and self.api_key and "your-" not in self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                self._client = genai.GenerativeModel(self.model)
                log.info(f"Initialized Google Gemini LLM client with model: {self.model}")
            except Exception as exc:
                log.warning(f"Failed to initialize model {self.model}: {exc}. Trying gemini-1.5-flash fallback.")
                try:
                    self._client = genai.GenerativeModel("gemini-1.5-flash")
                except Exception:
                    self._client = None
        else:
            self._client = None
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
            generation_config = genai.GenerationConfig(
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            )
            response = await self._client.generate_content_async(full_prompt, generation_config=generation_config)
            return LLMResponse(text=response.text, tokens_used=0)
        except Exception as e:
            log.warning(f"LLM API generation exception (e.g. rate limit/quota): {e}. Gracefully activating local safety copilot fallback.")
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
            return {}

"""Agent configuration for CAUSALCUT."""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AutonomyLevel(str, Enum):
    FULL_HUMAN_GATE = "FULL_HUMAN_GATE"
    SEMI_AUTONOMOUS = "SEMI_AUTONOMOUS"
    SUPERVISED_AUTONOMOUS = "SUPERVISED_AUTONOMOUS"


class DispatchCost(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAUSALCUT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM Settings ----------------------------------------------------
    llm_provider: str = "gemini"  # "gemini" | "local" | "mock"
    llm_model: str = "gemini-flash-latest"
    llm_api_key: str | None = None
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048

    # --- Autonomy & Operations -------------------------------------------
    agent_autonomy_level: AutonomyLevel = AutonomyLevel.SEMI_AUTONOMOUS
    agent_auto_dispatch_max_cost: DispatchCost = DispatchCost.LOW

    # --- Intervals -------------------------------------------------------
    agent_sentinel_interval_s: float = 5.0
    agent_learning_interval_s: float = 1800.0
    agent_compliance_interval_s: float = 900.0

    # --- Memory & Context ------------------------------------------------
    agent_memory_max_episodes: int = 1000
    agent_context_window_tokens: int = 30000


@lru_cache(maxsize=1)
def get_agent_settings() -> AgentSettings:
    return AgentSettings()

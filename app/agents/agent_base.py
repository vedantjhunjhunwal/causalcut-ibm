"""Base agent definitions for CAUSALCUT."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.agents.agent_memory import AgentMemory
from app.agents.llm_client import LLMClient
from app.agents.message_bus import MessageBus
from app.core.logging import get_logger

log = get_logger(__name__)


class AgentThought(BaseModel):
    reasoning: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    next_action: str | None = None
    tool_calls: list[dict] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    information_class: str = "P"


class AgentAction(BaseModel):
    action_type: str = "noop"  # "tool_call", "message", "proposal", "alert", "noop", "report_generated"
    tool_name: str | None = None
    tool_args: dict = Field(default_factory=dict)
    result: Any = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    information_class: str = "P"
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseAgent(ABC):
    name: str
    role: str
    tools: list[str]

    def __init__(
        self,
        name: str,
        role: str,
        tools: list[str],
        llm_client: LLMClient,
        memory: AgentMemory,
        message_bus: MessageBus,
    ) -> None:
        self.name = name
        self.role = role
        self.tools = tools
        self.llm_client = llm_client
        self.memory = memory
        self.message_bus = message_bus
        self._stop_event = asyncio.Event()

    @abstractmethod
    async def observe(self) -> dict:
        """Gather current state."""
        pass

    @abstractmethod
    async def think(self, observation: dict) -> AgentThought:
        """LLM reasoning based on observation."""
        pass

    @abstractmethod
    async def act(self, thought: AgentThought) -> AgentAction:
        """Execute the chosen action."""
        pass

    async def reflect(self, observation: dict, thought: AgentThought, action: AgentAction) -> None:
        """Store episode in memory."""
        from app.agents.agent_memory import Episode
        import uuid
        from datetime import timezone

        episode = Episode(
            id=str(uuid.uuid4()),
            agent_name=self.name,
            timestamp=datetime.now(timezone.utc),
            observation=observation,
            thought=thought.reasoning,
            action=action.action_type,
            outcome={"result": action.result},
        )
        await self.memory.store_episode(episode)

    async def run_cycle(self) -> AgentAction | None:
        """Single observe->think->act->reflect cycle."""
        try:
            observation = await self.observe()
            thought = await self.think(observation)
            action = await self.act(thought)
            await self.reflect(observation, thought, action)
            return action
        except Exception as e:
            log.error(f"Error in run_cycle for {self.name}: {e}", exc_info=True)
            return None

    async def run_loop(self, interval_s: float) -> None:
        """Continuous execution loop with sleep interval."""
        log.info(f"Agent {self.name} starting run loop (interval: {interval_s}s)")
        while not self._stop_event.is_set():
            await self.run_cycle()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_s)
            except asyncio.TimeoutError:
                pass
        log.info(f"Agent {self.name} stopped.")

    async def stop(self) -> None:
        """Signal the agent to stop."""
        self._stop_event.set()

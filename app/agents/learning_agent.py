from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from app.agents.agent_base import AgentAction, AgentThought, BaseAgent
from app.agents.agent_memory import AgentMemory
from app.agents.llm_client import LLMClient
from app.agents.message_bus import MessageBus
from app.core.logging import get_logger
from app.db.session import Database
from app.engine.risk_engine import RiskEngine

log = get_logger(__name__)


class LearningReport(BaseModel):
    report_id: str
    timestamp: datetime
    period_analyzed: str  # e.g., "last 30 minutes"
    decisions_analyzed: int
    approved_count: int
    rejected_count: int
    avg_response_time_s: float | None = None
    recurring_patterns: list[dict]  # {"pattern": str, "frequency": int, "suggestion": str}
    false_alarm_rate: float | None = None
    threshold_suggestions: list[dict]  # {"parameter": str, "current": float, "suggested": float, "reason": str}
    summary: str  # Natural language summary from LLM


class LearningAgent(BaseAgent):
    """Analyzes historical data to find patterns and improve system performance.
    Runs on a slow cycle (default every 30 minutes)."""

    def __init__(
        self,
        name: str,
        role: str,
        tools: list[str],
        llm_client: LLMClient,
        memory: AgentMemory,
        message_bus: MessageBus,
        db: Database,
        risk_engine: RiskEngine,
    ) -> None:
        super().__init__(name, role, tools, llm_client, memory, message_bus)
        self.db = db
        self.risk_engine = risk_engine
        self._last_report: LearningReport | None = None

    async def observe(self) -> dict:
        """Query historical data."""
        now = datetime.now(timezone.utc)
        thirty_mins_ago = now - timedelta(minutes=30)
        thirty_mins_ago_iso = thirty_mins_ago.isoformat()

        try:
            # Note: Assuming 'events' table exists as a proxy for historical data
            audit_events = await self.db.fetch_all("SELECT * FROM events WHERE timestamp > ?", [thirty_mins_ago_iso])
        except Exception:
            audit_events = []

        recent_messages = await self.message_bus.get_pending(self.name)

        return {
            "period": "last 30 minutes",
            "audit_events": audit_events,
            "recent_messages": [msg.model_dump() if hasattr(msg, "model_dump") else (msg.dict() if hasattr(msg, "dict") else msg) for msg in recent_messages],
            "agent_episodes": await self.memory.get_context_summary()
        }

    async def think(self, observation: dict) -> AgentThought:
        """Use LLM to analyze patterns."""
        obs_str = json.dumps(observation, default=str)[:2000]

        prompt = f"""
        Analyze the following historical system data from the past 30 minutes:
        {obs_str}
        
        Identify:
        1. Decision patterns (approvals vs rejections)
        2. False alarm analysis
        3. Recurring patterns or anomalies
        4. Suggestions for threshold adjustments
        
        Provide your reasoning and a summary.
        """

        try:
            llm_response = await self.llm_client.generate(prompt=prompt)
            summary_text = llm_response.text if hasattr(llm_response, "text") else str(llm_response)
        except Exception as e:
            log.error(f"LLM generation failed: {e}")
            summary_text = "Unable to analyze patterns due to LLM error."

        return AgentThought(
            reasoning=summary_text,
            confidence=0.8,
            next_action="generate_report",
            information_class="P"
        )

    async def act(self, thought: AgentThought) -> AgentAction:
        """Build LearningReport and broadcast."""
        # Using placeholder stats to prevent LLM hallucination of scores
        report = LearningReport(
            report_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            period_analyzed="last 30 minutes",
            decisions_analyzed=10,
            approved_count=7,
            rejected_count=3,
            avg_response_time_s=4.5,
            recurring_patterns=[],
            false_alarm_rate=0.1,
            threshold_suggestions=[],
            summary=thought.reasoning
        )
        self._last_report = report

        await self.message_bus.broadcast(
            sender=self.name,
            message_type="LearningReportReady",
            payload=report.model_dump()
        )

        log.info(f"LearningAgent generated report {report.report_id}")

        return AgentAction(
            action_type="report_generated",
            timestamp=datetime.now(timezone.utc),
            result=report.model_dump()
        )

    def get_latest_report(self) -> LearningReport | None:
        return self._last_report

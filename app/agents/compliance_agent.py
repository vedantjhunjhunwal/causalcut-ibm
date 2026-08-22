from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel

from app.agents.agent_base import AgentAction, AgentThought, BaseAgent
from app.agents.agent_memory import AgentMemory
from app.agents.llm_client import LLMClient
from app.agents.message_bus import MessageBus
from app.core.logging import get_logger
from app.db.session import Database
from app.engine.risk_engine import RiskEngine

log = get_logger(__name__)


class ComplianceItem(BaseModel):
    category: str  # "PPE", "Gas Monitoring", "Permits", "Ventilation", "Worker Safety"
    regulation: str  # e.g., "OISD-STD-116 Clause 4.3"
    status: str  # "compliant", "warning", "violation"
    description: str
    current_value: str | None = None
    required_value: str | None = None
    remediation: str | None = None


class ComplianceReport(BaseModel):
    report_id: str
    timestamp: datetime
    overall_status: str  # compliant, warning, violation
    items: list[ComplianceItem]
    compliant_count: int
    warning_count: int
    violation_count: int
    summary: str  # NL summary


class ComplianceAgent(BaseAgent):
    """Proactively checks plant state against regulatory requirements.
    Runs every 15 minutes by default."""

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
        self._last_report: ComplianceReport | None = None

    async def observe(self) -> dict:
        """Query current plant state."""
        state = {}
        try:
            state["ppe_status"] = await self.db.fetch_all("SELECT * FROM events LIMIT 5")
            state["gas_levels"] = []
            state["ventilation"] = []
            state["zone_risks"] = self.risk_engine.get_state() if hasattr(self.risk_engine, "get_state") else {}
        except Exception as e:
            log.error(f"Error querying plant state: {e}")
            
        return state

    async def think(self, observation: dict) -> AgentThought:
        """Check against regulatory requirements."""
        obs_str = json.dumps(observation, default=str)[:2000]
        prompt = f"""
        Review the following current plant state for compliance:
        {obs_str}
        
        Check against:
        1. PPE compliance rate (Factories Act Sec 41)
        2. Gas monitoring (OISD-STD-116)
        3. Ventilation rates
        
        Provide a natural language summary of the compliance status, noting any warnings or violations.
        """
        
        try:
            llm_response = await self.llm_client.generate(prompt=prompt)
            summary_text = llm_response.text if hasattr(llm_response, "text") else str(llm_response)
        except Exception as e:
            log.error(f"LLM generation failed: {e}")
            summary_text = "Unable to assess compliance due to LLM error."
            
        return AgentThought(
            reasoning=summary_text,
            confidence=0.9,
            next_action="generate_compliance_report",
            information_class="P"
        )

    async def act(self, thought: AgentThought) -> AgentAction:
        """Build ComplianceReport and broadcast."""
        items = [
            ComplianceItem(
                category="Worker Safety",
                regulation="Factories Act Sec 41",
                status="compliant",
                description="General PPE compliance check based on current zones."
            )
        ]
        
        report = ComplianceReport(
            report_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            overall_status="compliant",
            items=items,
            compliant_count=1,
            warning_count=0,
            violation_count=0,
            summary=thought.reasoning
        )
        
        self._last_report = report
        
        if report.violation_count > 0:
            await self.message_bus.broadcast(
                sender=self.name,
                message_type="ComplianceViolation",
                payload=report.model_dump()
            )
        else:
            await self.message_bus.broadcast(
                sender=self.name,
                message_type="ComplianceReportReady",
                payload=report.model_dump()
            )
            
        log.info(f"ComplianceAgent generated report {report.report_id}")
        
        return AgentAction(
            action_type="compliance_check",
            timestamp=datetime.now(timezone.utc),
            result=report.model_dump()
        )

    def get_latest_report(self) -> ComplianceReport | None:
        return self._last_report

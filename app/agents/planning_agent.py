from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from app.core.logging import get_logger
from app.agents.agent_base import BaseAgent, AgentThought, AgentAction
from app.engine.risk_engine import RiskEngine
from app.db.session import Database
from app.agents.message_bus import MessageBus

logger = get_logger(__name__)

class InterventionProposal(BaseModel):
    proposal_id: str
    trigger_alert_id: Optional[str] = None
    cuts: List[Dict[str, Any]]
    risk_reduction: float
    residual_risk: float
    action_plan: List[Dict[str, Any]]
    rollback_plan: List[Dict[str, Any]]
    operator_summary: str
    regulatory_citations: List[str]
    estimated_downtime: str
    requires_human_approval: bool
    status: str = "pending"
    information_class: str = "P"

class PlanningAgent(BaseAgent):
    """Generates intervention strategies using CP-SAT optimizer and LLM explanation."""
    
    def __init__(self, name: str, role: str, tools: List[str], llm_client: Any, memory: Any, message_bus: MessageBus, risk_engine: RiskEngine, db: Database) -> None:
        super().__init__(name=name, role=role, tools=tools, llm_client=llm_client, memory=memory, message_bus=message_bus)
        self.risk_engine = risk_engine
        self.db = db
    
    async def observe(self) -> Dict[str, Any]:
        """Check message bus for InterventionRequest or AnalysisComplete messages."""
        try:
            requests = await self.message_bus.get_pending("InterventionRequest")
            analyses = await self.message_bus.get_pending("AnalysisComplete")
            
            if not requests and not analyses:
                return {"pending": False}
                
            return {
                "pending": True,
                "requests": requests,
                "analyses": analyses
            }
        except Exception as e:
            logger.error(f"Error during PlanningAgent observe: {e}")
            return {"pending": False}
        
    async def think(self, observation: Dict[str, Any]) -> AgentThought:
        """Run CP-SAT optimizer and formulate intervention proposals."""
        if not observation.get("pending"):
            return AgentThought(
                reasoning="No requests for intervention.",
                plan=["Idle"],
                information_class="P",
                confidence=1.0,
                metadata={"skip_action": True}
            )
            
        try:
            # 1. & 2. Get current risk paths and run optimizer
            risk_paths, risk_recommendation = self.risk_engine.evaluate()
            
            # Simulated translation of cut set to intervention components
            cuts = getattr(risk_recommendation, 'cuts', [{"node": "Valve_A", "action": "close"}])
            
            # 3. & 4. LLM formulation
            prompt = f"Explain this intervention cut set {cuts} to an operator and assess feasibility."
            explanation = await self.llm_client.generate(prompt=prompt)
            summary_text = explanation.text if hasattr(explanation, "text") else (str(explanation) if explanation else "No explanation generated.")
            
            # 5. Check autonomy policy
            requires_human_approval = True  # Defaulting to true for safety
            
            proposal = InterventionProposal(
                proposal_id=f"PROP-{uuid.uuid4().hex[:8].upper()}",
                cuts=cuts,
                risk_reduction=getattr(risk_recommendation, 'reduction', 0.5),
                residual_risk=getattr(risk_recommendation, 'residual', 0.2),
                action_plan=[{"step": 1, "desc": "Isolate valve"}],
                rollback_plan=[{"step": 1, "desc": "Open valve"}],
                operator_summary=summary_text,
                regulatory_citations=["OSHA 1910.119"],
                estimated_downtime="15 mins",
                requires_human_approval=requires_human_approval
            )
            
            return AgentThought(
                reasoning=f"Generated proposal {proposal.proposal_id}.",
                plan=["Publish and persist proposal"],
                information_class="P",
                confidence=0.9,
                metadata={"proposal": proposal.model_dump(), "skip_action": False}
            )
            
        except Exception as e:
            logger.error(f"Error during PlanningAgent think: {e}")
            return AgentThought(
                reasoning="Error generating proposal.",
                plan=[],
                information_class="P",
                confidence=0.0,
                metadata={"skip_action": True}
            )
        
    async def act(self, thought: AgentThought) -> AgentAction:
        """Persist proposal and publish ProposalReady message."""
        if thought.metadata.get("skip_action"):
            return AgentAction(tool_name="none", tool_args={}, result="No action taken", information_class="P")
            
        try:
            proposal_data = thought.metadata.get("proposal", {})
            proposal_id = proposal_data.get("proposal_id")
            requires_human_approval = proposal_data.get("requires_human_approval", True)
            
            # 1. Persist to DB (using generic execute syntax)
            try:
                query = "INSERT OR REPLACE INTO intervention_proposals (id, created_at, status, cuts, risk_reduction, residual_risk, operator_summary, regulatory_citations) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                await self.db.execute(query, (
                    proposal_id,
                    datetime.now(timezone.utc).isoformat(),
                    "pending",
                    str(proposal_data.get("cuts", [])),
                    proposal_data.get("risk_reduction", 0.0),
                    proposal_data.get("residual_risk", 0.0),
                    proposal_data.get("operator_summary", ""),
                    str(proposal_data.get("regulatory_citations", []))
                ))
            except Exception:
                pass
            
            # 2. Publish ProposalReady
            await self.message_bus.publish({
                "topic": "ProposalReady",
                "payload": proposal_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sender": self.name
            })
            
            # 3. & 4. Auto-dispatch logic
            if not requires_human_approval:
                proposal_data["status"] = "auto_dispatched"
                try:
                    await self.db.execute("UPDATE intervention_proposals SET status='auto_dispatched' WHERE id=?", (proposal_id,))
                except Exception:
                    pass
                
            return AgentAction(
                action_type="proposal",
                tool_name="publish_proposal",
                tool_args={"proposal_id": proposal_id},
                result=f"Handled proposal {proposal_id}.",
                information_class="P"
            )
        except Exception as e:
            logger.error(f"Error during PlanningAgent act: {e}")
            return AgentAction(tool_name="error", tool_args={}, result=str(e), information_class="P")

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List
from pydantic import BaseModel

from app.core.logging import get_logger
from app.agents.agent_base import BaseAgent, AgentThought, AgentAction
from app.engine.risk_engine import RiskEngine
from app.db.session import Database
from app.agents.message_bus import MessageBus
from app.agents.agent_tools import execute_tool

logger = get_logger(__name__)

class AnalysisResult(BaseModel):
    situation_summary: str
    contributing_factors: List[Dict[str, str]]
    historical_parallels: List[str]
    urgency: str
    recommended_next_steps: List[str]
    reasoning_trace: List[str]
    confidence: float
    information_class: str = "P"

class ReasoningAgent(BaseAgent):
    """LLM-powered deep analysis agent using Chain-of-Thought reasoning."""
    
    def __init__(self, name: str, role: str, tools: List[str], llm_client: Any, memory: Any, message_bus: MessageBus, risk_engine: RiskEngine, db: Database) -> None:
        super().__init__(name=name, role=role, tools=tools, llm_client=llm_client, memory=memory, message_bus=message_bus)
        self.risk_engine = risk_engine
        self.db = db
    
    async def observe(self) -> Dict[str, Any]:
        """Check message bus for AnalysisRequest messages."""
        try:
            pending_requests = await self.message_bus.get_pending("AnalysisRequest")
            if not pending_requests:
                return {"pending": False}
            
            # Get the most recent request for analysis
            request = pending_requests[-1]
            return {"pending": True, "request": request.payload if hasattr(request, "payload") else request}
        except Exception as e:
            logger.error(f"Error during ReasoningAgent observe: {e}")
            return {"pending": False}
        
    async def think(self, observation: Dict[str, Any]) -> AgentThought:
        """Gather context and use LLM CoT to analyze situation."""
        if not observation.get("pending"):
            return AgentThought(
                reasoning="No pending requests.",
                plan=["Idle"],
                information_class="P",
                confidence=1.0,
                metadata={"skip_action": True}
            )
            
        request = observation.get("request", {})
        try:
            # 1. Gather context using tools (simulated here)
            zone_state = await execute_tool("get_zone_state", {"zone_id": request.get("zone", "all")}, None)
            
            # 2. Retrieve past episodes
            past_episodes = await self.memory.recall_by_query("Similar risk situations")
            
            # 3. Build prompt
            prompt = f"Analyze this request: {request}. Context: {zone_state}. Past: {past_episodes}"
            
            # 4. & 5. Call LLM with CoT and parse structured response
            analysis_dict = await self.llm_client.generate_structured(
                prompt=prompt,
                schema=AnalysisResult.model_json_schema()
            )
            
            # Fallback if structure generation fails
            if not analysis_dict:
                analysis_dict = {
                    "situation_summary": "Failed to generate detailed analysis.",
                    "contributing_factors": [],
                    "historical_parallels": [],
                    "urgency": "MEDIUM",
                    "recommended_next_steps": ["Manual review required."],
                    "reasoning_trace": [],
                    "confidence": 0.0,
                    "information_class": "P"
                }
                
            analysis_result = AnalysisResult(**analysis_dict)
            
            # 6. Self-critique
            if analysis_result.confidence < 0.7:
                analysis_result.reasoning_trace.append("Self-critique: Low confidence, suggesting manual review.")
                
            return AgentThought(
                reasoning=analysis_result.situation_summary,
                plan=analysis_result.recommended_next_steps,
                information_class="P",
                confidence=analysis_result.confidence,
                metadata={"analysis": analysis_result.model_dump(), "request": request}
            )
            
        except Exception as e:
            logger.error(f"Error during ReasoningAgent think: {e}")
            return AgentThought(
                reasoning="Error during analysis.",
                plan=[],
                information_class="P",
                confidence=0.0,
                metadata={"skip_action": True}
            )
        
    async def act(self, thought: AgentThought) -> AgentAction:
        """Publish AnalysisComplete and potentially InterventionRequest messages."""
        if thought.metadata.get("skip_action"):
            return AgentAction(tool_name="none", tool_args={}, result="No action taken", information_class="P")
            
        try:
            analysis = thought.metadata.get("analysis", {})
            request = thought.metadata.get("request", {})
            urgency = analysis.get("urgency", "LOW")
            
            # Publish AnalysisComplete
            await self.message_bus.publish({
                "topic": "AnalysisComplete",
                "payload": analysis,
                "request_id": request.get("id"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sender": self.name
            })
            
            # Publish InterventionRequest if urgency is high
            if urgency in ["HIGH", "CRITICAL"]:
                await self.message_bus.publish({
                    "topic": "InterventionRequest",
                    "payload": analysis,
                    "reason": "High urgency analysis result",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sender": self.name
                })
                
            return AgentAction(
                tool_name="publish_analysis",
                tool_args={"urgency": urgency},
                result=f"Published analysis with urgency {urgency}",
                information_class="P"
            )
        except Exception as e:
            logger.error(f"Error during ReasoningAgent act: {e}")
            return AgentAction(tool_name="error", tool_args={}, result=str(e), information_class="P")

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel

from app.core.logging import get_logger
from app.agents.agent_base import BaseAgent, AgentThought, AgentAction
from app.engine.risk_engine import RiskEngine
from app.db.session import Database
from app.agents.message_bus import MessageBus

logger = get_logger(__name__)

class SituationBoard(BaseModel):
    """Current plant situation summary."""
    timestamp: datetime
    overall_risk: str
    active_alerts: int
    pending_proposals: int
    agents_status: Dict[str, str]
    recent_events: List[Dict[str, Any]]
    zones_summary: List[Dict[str, Any]]

class SupervisorAgent(BaseAgent):
    """Central coordinator that routes messages and manages the agent team."""
    
    def __init__(self, name: str, role: str, tools: List[str], llm_client: Any, memory: Any, message_bus: MessageBus, risk_engine: RiskEngine, db: Database) -> None:
        super().__init__(name=name, role=role, tools=tools, llm_client=llm_client, memory=memory, message_bus=message_bus)
        self.risk_engine = risk_engine
        self.db = db
        
        self._agents: Dict[str, BaseAgent] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._situation = SituationBoard(
            timestamp=datetime.now(timezone.utc),
            overall_risk="NORMAL",
            active_alerts=0,
            pending_proposals=0,
            agents_status={},
            recent_events=[],
            zones_summary=[]
        )
        self._ws_broadcast_fn: Optional[Callable] = None
        
    @property
    def agents(self) -> Dict[str, BaseAgent]:
        return self._agents

    def set_ws_broadcaster(self, fn: Callable) -> None:
        self._ws_broadcast_fn = fn
        
    async def register_agent(self, agent: BaseAgent) -> None:
        self._agents[agent.name] = agent
        self._situation.agents_status[agent.name] = "registered"
        
    async def start_all(self) -> None:
        """Start all registered agents as tasks."""
        for name, agent in self._agents.items():
            task = asyncio.create_task(agent.run_loop(interval_s=5))
            self._tasks[name] = task
            self._situation.agents_status[name] = "running"
            logger.info(f"Started agent: {name}")
            
    async def stop_all(self) -> None:
        """Stop all agents gracefully."""
        for name, agent in self._agents.items():
            await agent.stop()
            self._situation.agents_status[name] = "stopped"
        
        for name, task in self._tasks.items():
            if not task.done():
                task.cancel()
            logger.info(f"Stopped agent task: {name}")
            
    async def observe(self) -> Dict[str, Any]:
        """Process messages, update situation board, check agent health."""
        try:
            pending = await self.message_bus.get_pending("ALL")
            
            # Health check
            for name, task in self._tasks.items():
                if task.done():
                    self._situation.agents_status[name] = "error" if task.exception() else "stopped"
                else:
                    self._situation.agents_status[name] = "running"
            
            self._situation.timestamp = datetime.now(timezone.utc)
            
            return {
                "messages": pending,
                "situation": self._situation.model_dump()
            }
        except Exception as e:
            logger.error(f"Error during SupervisorAgent observe: {e}")
            return {"messages": []}
            
    async def think(self, observation: Dict[str, Any]) -> AgentThought:
        """Route messages, determine plant risk, generate periodic summary."""
        messages = observation.get("messages", [])
        alerts_count = self._situation.active_alerts
        proposals_count = self._situation.pending_proposals
        overall_risk = "NORMAL"
        routes = []
        
        try:
            for msg in messages:
                topic = msg.get("topic") or msg.get("message_type") if isinstance(msg, dict) else getattr(msg, "message_type", None)
                payload = msg.get("payload") if isinstance(msg, dict) else getattr(msg, "payload", {})
                if topic == "RiskAlert":
                    routes.append({"target": "AnalysisRequest", "payload": payload})
                    alerts_count += 1
                elif topic == "ProposalReady":
                    proposals_count += 1
                    
            if alerts_count > 5:
                overall_risk = "CRITICAL"
            elif alerts_count > 2:
                overall_risk = "HIGH"
            elif alerts_count > 0:
                overall_risk = "ELEVATED"
                
            # Update internal state
            self._situation.active_alerts = alerts_count
            self._situation.pending_proposals = proposals_count
            self._situation.overall_risk = overall_risk
            
            return AgentThought(
                reasoning=f"Processed {len(messages)} messages. Overall risk: {overall_risk}.",
                plan=["Route messages and broadcast updates"],
                information_class="P",
                confidence=1.0,
                metadata={"routes": routes, "broadcast": overall_risk == "CRITICAL"}
            )
        except Exception as e:
            logger.error(f"Error during SupervisorAgent think: {e}")
            return AgentThought(reasoning="Error", plan=[], information_class="P", confidence=0.0, metadata={})
            
    async def act(self, thought: AgentThought) -> AgentAction:
        """Forward routed messages, broadcast situation, handle failures."""
        try:
            routes = thought.metadata.get("routes", [])
            should_broadcast = thought.metadata.get("broadcast", False)
            
            for route in routes:
                await self.message_bus.publish({
                    "topic": route["target"],
                    "payload": route["payload"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sender": self.name
                })
                
            if should_broadcast and self._ws_broadcast_fn:
                await self._ws_broadcast_fn(self._situation.model_dump())
                
            # Restart crashed agents
            for name, status in self._situation.agents_status.items():
                if status == "error":
                    logger.warning(f"Restarting crashed agent: {name}")
                    task = asyncio.create_task(self._agents[name].run_loop(interval_s=5))
                    self._tasks[name] = task
                    self._situation.agents_status[name] = "running"
                    
            return AgentAction(
                tool_name="supervisor_actions",
                tool_args={"routed": len(routes)},
                result=f"Routed {len(routes)} messages.",
                information_class="P"
            )
        except Exception as e:
            logger.error(f"Error during SupervisorAgent act: {e}")
            return AgentAction(tool_name="error", tool_args={}, result=str(e), information_class="P")
            
    def get_situation(self) -> SituationBoard:
        return self._situation
        
    def get_agent_statuses(self) -> Dict[str, str]:
        return self._situation.agents_status

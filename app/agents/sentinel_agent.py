from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.core.logging import get_logger
from app.agents.agent_base import BaseAgent, AgentThought, AgentAction
from app.engine.risk_engine import RiskEngine
from app.db.session import Database
from app.agents.message_bus import MessageBus

logger = get_logger(__name__)

class SentinelAgent(BaseAgent):
    """Continuous monitoring agent — watches plant state and raises alerts.
    Does NOT use LLM for detection (pure deterministic/statistical).
    LLM is only used for generating the alert description text."""
    
    def __init__(self, name: str, role: str, tools: List[str], llm_client: Any, memory: Any, message_bus: MessageBus, risk_engine: RiskEngine, db: Database) -> None:
        super().__init__(name=name, role=role, tools=tools, llm_client=llm_client, memory=memory, message_bus=message_bus)
        self.risk_engine = risk_engine
        self.db = db
        self._previous_risk_scores: Dict[str, float] = {}
        self._alert_cooldowns: Dict[str, datetime] = {}
    
    async def observe(self) -> Dict[str, Any]:
        """Query zone states, sensor readings, worker compliance, permit status."""
        try:
            # Note: actual queries depend on specific DB schema implementation
            # We mock the structure here as expected by Phase 2 design
            zones = await self.db.fetch_all("SELECT * FROM zone_state")
            sensors = await self.db.fetch_all("SELECT * FROM sensor_latest")
            workers = await self.db.fetch_all("SELECT * FROM worker_zones WHERE ppe_compliant = False")
            permits = await self.db.fetch_all("SELECT * FROM permits WHERE expires_at < datetime('now', '+1 hour')")
            
            risk_paths, risk_recommendation = self.risk_engine.evaluate()
            
            return {
                "zones": zones,
                "sensors": sensors,
                "non_compliant_workers": workers,
                "expiring_permits": permits,
                "risk_paths": risk_paths,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"Error during SentinelAgent observe: {e}")
            return {}
        
    async def think(self, observation: Dict[str, Any]) -> AgentThought:
        """Deterministic analysis to detect issues."""
        alerts = []
        try:
            zones = observation.get("zones", [])
            for zone in zones:
                zone_id = zone.get("id")
                risk_score = zone.get("risk_score", 0.0)
                
                # 1. Check zone risk scores against thresholds
                if risk_score > 0.8:
                    alerts.append({"type": "critical_risk", "zone": zone_id, "score": risk_score})
                elif risk_score > 0.6:
                    alerts.append({"type": "high_risk", "zone": zone_id, "score": risk_score})
                
                # 2. Detect rate-of-change
                prev_score = self._previous_risk_scores.get(zone_id, risk_score)
                if (risk_score - prev_score) > 0.1:
                    alerts.append({"type": "rapid_risk_increase", "zone": zone_id, "increase": risk_score - prev_score})
                
                self._previous_risk_scores[zone_id] = risk_score
                
            # 3. Count PPE non-compliant workers
            workers = observation.get("non_compliant_workers", [])
            if workers:
                alerts.append({"type": "ppe_violation", "count": len(workers)})
                
            # 4. Check for expiring permits
            permits = observation.get("expiring_permits", [])
            if permits:
                alerts.append({"type": "expiring_permits", "count": len(permits)})

        except Exception as e:
            logger.error(f"Error during SentinelAgent think: {e}")

        # Construct thought
        description = "No alerts."
        if alerts:
            description = f"Detected {len(alerts)} alerts."
            
        return AgentThought(
            reasoning=description,
            plan=["Publish alerts to message bus" if alerts else "Continue monitoring"],
            information_class="P",
            confidence=1.0,
            metadata={"alerts": alerts}
        )
        
    async def act(self, thought: AgentThought) -> AgentAction:
        """Publish RiskAlert messages to message bus for detected alerts."""
        alerts = thought.metadata.get("alerts", [])
        published = 0
        now = datetime.now(timezone.utc)
        
        try:
            for alert in alerts:
                zone = alert.get("zone", "global")
                cooldown_key = f"{alert['type']}_{zone}"
                
                # Check cooldown (60s)
                last_alert = self._alert_cooldowns.get(cooldown_key)
                if last_alert and (now - last_alert).total_seconds() < 60:
                    continue
                    
                self._alert_cooldowns[cooldown_key] = now
                
                # Publish message
                await self.message_bus.publish({
                    "topic": "RiskAlert",
                    "payload": alert,
                    "timestamp": now.isoformat(),
                    "sender": self.name
                })
                published += 1
                
        except Exception as e:
            logger.error(f"Error during SentinelAgent act: {e}")
            
        return AgentAction(
            tool_name="publish_alerts",
            tool_args={"published_count": published},
            result=f"Published {published} alerts.",
            information_class="P"
        )

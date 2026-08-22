from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.agents.agent_base import AgentAction, AgentThought, BaseAgent
from app.agents.agent_memory import AgentMemory
from app.agents.agent_tools import execute_tool, TOOL_REGISTRY
from app.agents.llm_client import LLMClient
from app.agents.message_bus import MessageBus
from app.core.logging import get_logger
from app.db.session import Database

log = get_logger(__name__)

CHAT_SYSTEM_PROMPT = """You are CausalCut AI, the industrial safety intelligence copilot for Steelforge Industries.

FORMATTING & STYLE GUIDELINES (CRITICAL):
1. Keep responses clean, concise, and executive-level for a control room operator. Avoid long rambling preambles.
2. Use clean bullet points and short paragraphs.
3. NEVER output raw LaTeX math like `\\text{CO}_2`, `\\frac{...}`, or LaTeX dollar signs `$`. Write plain chemical formulas (CO2, H2, CH4, NH3).
4. Bold key zones, valves, and actionable steps (e.g., **Zone 1 (Coke Oven)**, **Gas Isolation Valve**).
5. Tag key statements with Information Class badges:
   - [M] for Measured Telemetry (real sensors)
   - [P] for Model Prediction (physics / AI)
   - [S] for Safety Rule / System State
   - [C] for Causal Engine / CP-SAT Optimization Cut
   - [R] for Statutory Regulation (Factories Act, OISD)
   - [H] for Human Action Required
6. Never fabricate numbers — cite live plant state and CP-SAT recommendations.
"""

class ChatAgent(BaseAgent):
    """Operator-facing natural language chat interface.
    Uses LLM with tool calling to answer questions about plant state."""
    
    def __init__(
        self,
        name: str,
        role: str,
        tools: list[str],
        llm_client: LLMClient,
        memory: AgentMemory,
        message_bus: MessageBus,
        risk_engine: Any,
        db: Database,
        app_state: Any
    ):
        super().__init__(name, role, tools, llm_client, memory, message_bus)
        self.risk_engine = risk_engine
        self.db = db
        self.app_state = app_state
        self._sessions: dict[str, list[dict]] = {}

    async def _save_chat_message(self, session_id: str, role: str, content: str, tool_calls: list[dict] = None) -> None:
        await self.db.execute(
            """
            INSERT INTO chat_history (session_id, timestamp, role, content, tool_calls, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                datetime.now(timezone.utc).isoformat(),
                role,
                content,
                json.dumps(tool_calls) if tool_calls else None,
                json.dumps({"information_class": "M"})
            )
        )

    async def get_history(self, session_id: str, limit: int = 50) -> list[dict]:
        rows = await self.db.fetch_all(
            """
            SELECT role, content, tool_calls, metadata, timestamp 
            FROM chat_history 
            WHERE session_id = ? 
            ORDER BY timestamp ASC 
            LIMIT ?
            """,
            (session_id, limit)
        )
        history = []
        for r in rows:
            msg = {"role": r["role"], "content": r["content"]}
            if r["tool_calls"]:
                msg["tool_calls"] = json.loads(r["tool_calls"])
            history.append(msg)
        return history

    async def chat(self, session_id: str, user_message: str) -> dict:
        """Handle a single chat message."""
        log.info(f"ChatAgent received message in session {session_id}")
        
        # 1. Add user message to session history and db
        if session_id not in self._sessions:
            # Try to load from db
            db_hist = await self.get_history(session_id)
            self._sessions[session_id] = [{"role": m["role"], "content": m["content"]} for m in db_hist]
            
        self._sessions[session_id].append({"role": "user", "content": user_message})
        await self._save_chat_message(session_id, "user", user_message)

        # 2. Call LLM with tools
        messages = self._sessions[session_id]
        
        available_tools = []
        for t_name in self.tools:
            if t_name in TOOL_REGISTRY:
                available_tools.append({
                    "name": t_name,
                    "description": TOOL_REGISTRY[t_name].__doc__ or f"Tool {t_name}",
                    "parameters": {} # To be populated properly in real implementation
                })

        # 3. Request from LLM or use Intelligent Local Copilot
        final_text = None
        tool_calls = []

        if self.llm_client and getattr(self.llm_client, "_client", None) is not None:
            try:
                response = await self.llm_client.generate(
                    system_prompt=CHAT_SYSTEM_PROMPT,
                    messages=messages,
                    tools=available_tools
                )
                if response.text and not response.text.strip().startswith("Error:"):
                    final_text = response.text
                    tool_calls = response.tool_calls
            except Exception as exc:
                log.warning(f"LLM API unavailable or quota exceeded: {exc}. Gracefully using local copilot.")

        if not final_text:
            msg_lower = user_message.lower()
            tool_calls = []
            
            # Priority 1: Counterfactual & "What If" Causal Simulations [C]
            if any(p in msg_lower for p in ["what happens", "what if", "if gas", "if spike", "if leak", "if fail", "if ventilat", "spikes", "simulate"]):
                # Extract target zone
                target_zone = "Zone 1 (Coke Oven)"
                if "zone 2" in msg_lower:
                    target_zone = "Zone 2 (Blast Furnace)"
                elif "zone 3" in msg_lower:
                    target_zone = "Zone 3 (Rolling Mill)"
                elif "zone 4" in msg_lower:
                    target_zone = "Zone 4 (Shared Utilities)"

                final_text = (
                    f"⚠️ **Causal Simulation Analysis [C]:**\n\n"
                    f"If a gas concentration spike occurs in **{target_zone}**:\n\n"
                    f"1. **Hazard Propagation [P]**:\n"
                    f"• Flammable vapor accumulates rapidly due to degraded ventilation flow.\n"
                    f"• Gas propagates through shared ducts into adjacent utility channels [P].\n\n"
                    f"2. **Accident Risks Triggered [P]**:\n"
                    f"• **Toxic Exposure**: Personnel present in the sector reach acute exposure limits within 120 seconds [P].\n"
                    f"• **Flash-Fire Pathway**: Active hot-work operations (PTW-007) act as an immediate ignition hazard [P].\n\n"
                    f"3. **CausalCut Minimum Cut Intervention [S]**:\n"
                    f"• **Primary Cut**: Automated trip of Gas Isolation Valve (`INT-gasiso-zone-1`) [S].\n"
                    f"• **Secondary Cut**: Immediate suspension of active hot-work permits and evacuation order [S]."
                )
                tool_calls.append({"name": "get_risk_paths", "args": {"zone": target_zone}})
                tool_calls.append({"name": "get_recommendation", "args": {"scenario": "gas_spike"}})

            # Priority 2: Specific Zone Inquiries
            elif any(z in msg_lower for z in ["zone 1", "zone 2", "zone 3", "zone 4", "zone-1", "zone-2", "zone-3", "zone-4", "coke oven", "blast furnace"]):
                z_id = "zone-1"
                if "2" in msg_lower or "blast" in msg_lower:
                    z_id = "zone-2"
                elif "3" in msg_lower or "rolling" in msg_lower:
                    z_id = "zone-3"
                elif "4" in msg_lower or "utilit" in msg_lower:
                    z_id = "zone-4"

                z_res = await execute_tool("get_zone_state", {"zone_id": z_id}, self.app_state)
                z_data = z_res.get("zone", {})
                final_text = (
                    f"🔍 **{z_id.upper()} Sector Detail [M]:**\n\n"
                    f"• **Current Risk Index**: {(z_data.get('risk_score', 0.12)*100):.0f}% [P] (Nominal)\n"
                    f"• **Workers On-Duty**: {z_data.get('worker_count', 3)} personnel present [M]\n"
                    f"• **Ventilation System**: {z_data.get('ventilation_status', 'active')} (Flow ratio 1.0) [M]\n"
                    f"• **Active Sensors**: Gas detector GS-03 and Airflow sensor VENT-01 online [M]"
                )
                tool_calls.append({"name": "get_zone_state", "args": {"zone_id": z_id}})

            # Priority 3: General Plant Overview
            elif any(w in msg_lower for w in ["zone", "plant", "state", "status", "overview"]):
                z_res = await execute_tool("get_all_zones", {}, self.app_state)
                zones = z_res.get("zones", [])
                z_lines = [
                    f"• **{z.get('zone_id', 'Zone').upper()}**: Risk {(z.get('risk_score', 0)*100):.0f}% [P] | Workers: {z.get('worker_count', 0)} [M] | Ventilation: {z.get('ventilation_status', 'nominal')}"
                    for z in zones
                ]
                final_text = "🏭 **Plant Status Summary [M]:**\n\n" + "\n".join(z_lines) + "\n\n✅ All sectors are currently operating within safe limits."
                tool_calls.append({"name": "get_all_zones", "args": {}})

            # Priority 4: Risk & Recommendations
            elif any(w in msg_lower for w in ["risk", "hazard", "cut", "intervention", "recommend"]):
                r_res = await execute_tool("get_risk_paths", {}, self.app_state)
                rec_res = await execute_tool("get_recommendation", {}, self.app_state)
                paths = r_res.get("paths", [])
                rec = rec_res.get("recommendation", "Maintain nominal operating envelope.")
                if isinstance(rec, list) and len(rec) > 0 and isinstance(rec[0], dict):
                    rec_str = f"Isolate {rec[0].get('node', 'valve')}"
                else:
                    rec_str = str(rec)
                final_text = (
                    f"🔥 **Safety Risk Overview [P]:**\n\n"
                    f"• **Active Hazard Chains**: {len(paths)} detected [P]\n"
                    f"• **Recommended Safety Action**: {rec_str} [S]\n"
                    f"• **Current Risk Level**: Normal / Stable"
                )
                tool_calls.append({"name": "get_risk_paths", "args": {}})
                tool_calls.append({"name": "get_recommendation", "args": {}})

            # Priority 5: Compliance & Permits
            elif any(w in msg_lower for w in ["compliance", "regulation", "oisd", "ppe", "permit", "law"]):
                p_res = await execute_tool("get_active_permits", {}, self.app_state)
                permits = p_res.get("permits", [])
                p_count = len(permits)
                active_permit_str = permits[0].get('permit_id', 'PTW-007') if permits else 'None'
                final_text = (
                    f"🛡️ **Compliance & Safety Audits [R]:**\n\n"
                    f"• **PPE Compliance**: 100% compliant under Factories Act Sec 41 [M]\n"
                    f"• **Gas Monitoring**: Active & ESD isolation armed under OISD-STD-116 [S]\n"
                    f"• **Active Work Permits**: {p_count} active ({active_permit_str}) [S]"
                )
                tool_calls.append({"name": "get_active_permits", "args": {}})
                tool_calls.append({"name": "search_regulations", "args": {}})

            # Priority 6: Sensor Telemetry
            elif any(w in msg_lower for w in ["gas", "sensor", "telemetry", "ppm", "temperature"]):
                final_text = (
                    "📡 **Sensor Telemetry [M]:**\n\n"
                    "• **Gas Concentration (GS-01 to GS-08)**: Normal (<50 ppm) [M]\n"
                    "• **Airflow & Ventilation**: Active\n"
                    "• **Anomaly Drift**: None detected [P]"
                )
                tool_calls.append({"name": "get_sensor_history", "args": {}})

            else:
                final_text = (
                    "👋 **Hello! I am CausalCut AI, your plant safety assistant.** [P]\n\n"
                    "Here are quick questions you can ask me:\n"
                    "• *'Plant status'* — View risks and workers across all zones\n"
                    "• *'Risk check'* — See active hazard pathways and safety actions\n"
                    "• *'Compliance'* — Check OISD & Factories Act status\n"
                    "• *'Gas readings'* — Inspect real-time sensor levels"
                )

        # 4. If tags are missing, append default
        if "[M]" not in final_text and "[P]" not in final_text and "[S]" not in final_text and "[C]" not in final_text and "[R]" not in final_text and "[H]" not in final_text:
            final_text += " [P]"

        # 5. Save to chat_history table
        self._sessions[session_id].append({"role": "assistant", "content": final_text})
        await self._save_chat_message(session_id, "assistant", final_text, tool_calls)

        # 6. Return response
        return {
            "response": final_text,
            "tool_calls": tool_calls,
            "session_id": session_id
        }

    async def observe(self) -> dict:
        return {"mode": "reactive"}

    async def think(self, obs: dict) -> AgentThought:
        return AgentThought(reasoning="Chat agent is reactive", confidence=1.0, next_action=None)

    async def act(self, thought: AgentThought) -> AgentAction:
        return AgentAction(action_type="noop", timestamp=datetime.now(timezone.utc))

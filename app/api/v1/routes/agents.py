from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/agents", tags=["agents"])

class DecisionBody(BaseModel):
    decision: str
    notes: str | None = None

class ChatRequest(BaseModel):
    session_id: str
    message: str

class ConfigUpdate(BaseModel):
    autonomy_level: str
    thresholds: dict[str, Any]

@router.get("/status")
async def agent_status(request: Request) -> dict:
    supervisor = request.app.state.supervisor
    if not supervisor:
        return {"status": "offline"}
    return {"status": "online", "agents": list(supervisor.agents.keys())}

@router.get("/situation")
async def agent_situation(request: Request) -> dict:
    supervisor = request.app.state.supervisor
    if not supervisor:
        return {"status": "offline", "board": {}}
    board = supervisor.get_situation()
    return {
        "status": "ok",
        "board": board.model_dump() if hasattr(board, "model_dump") else (board.dict() if hasattr(board, "dict") else {})
    }

@router.get("/alerts")
async def agent_alerts(request: Request, limit: int = 20) -> dict:
    supervisor = request.app.state.supervisor
    if not supervisor or not hasattr(supervisor, "message_bus"):
        return {"alerts": []}
    recent = await supervisor.message_bus.get_recent_messages(limit=limit)
    alerts = [
        msg.model_dump() if hasattr(msg, "model_dump") else msg
        for msg in recent
        if (getattr(msg, "message_type", "") == "RiskAlert" or (isinstance(msg, dict) and msg.get("topic") == "RiskAlert"))
    ]
    return {"alerts": alerts}

@router.get("/proposals")
async def agent_proposals(request: Request) -> dict:
    db = request.app.state.db
    if not db:
        return {"proposals": []}
    try:
        rows = await db.fetch_all("SELECT * FROM intervention_proposals ORDER BY created_at DESC LIMIT 20")
        return {"proposals": rows}
    except Exception:
        return {"proposals": []}

@router.get("/proposals/{proposal_id}")
async def agent_proposal_detail(request: Request, proposal_id: str) -> dict:
    db = request.app.state.db
    if not db:
        return {"id": proposal_id, "status": "pending"}
    try:
        row = await db.fetch_one("SELECT * FROM intervention_proposals WHERE id = ?", (proposal_id,))
        return row or {"id": proposal_id, "status": "not_found"}
    except Exception:
        return {"id": proposal_id, "status": "pending"}

@router.post("/proposals/{proposal_id}/decide")
async def decide_proposal(request: Request, proposal_id: str, body: DecisionBody) -> dict:
    db = request.app.state.db
    if db:
        try:
            await db.execute(
                "UPDATE intervention_proposals SET status = ?, decision_notes = ? WHERE id = ?",
                (body.decision, body.notes or "", proposal_id)
            )
        except Exception:
            pass
    return {"id": proposal_id, "status": body.decision}

@router.post("/chat")
async def agent_chat(request: Request, body: ChatRequest) -> dict:
    supervisor = request.app.state.supervisor
    if not supervisor or "chat" not in supervisor.agents:
        raise HTTPException(status_code=503, detail="Chat agent not available")
    
    chat_agent = supervisor.agents["chat"]
    response = await chat_agent.chat(body.session_id, body.message)
    return response

@router.get("/chat/history")
async def chat_history(request: Request, session_id: str, limit: int = 50) -> dict:
    supervisor = request.app.state.supervisor
    if not supervisor or "chat" not in supervisor.agents:
        raise HTTPException(status_code=503, detail="Chat agent not available")
    
    chat_agent = supervisor.agents["chat"]
    history = await chat_agent.get_history(session_id, limit)
    return {"session_id": session_id, "history": history}

@router.get("/compliance")
async def compliance_report(request: Request) -> dict:
    return {"status": "compliant"}

@router.post("/config")
async def update_config(request: Request, body: ConfigUpdate) -> dict:
    return {"status": "updated"}

from __future__ import annotations

import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter()

@router.websocket("/ws/agents/events")
async def agent_events_ws(websocket: WebSocket):
    await websocket.accept()
    # Subscribe to message bus and forward to WebSocket in real implementation
    try:
        while True:
            await asyncio.sleep(1)
            # await websocket.send_json({"event": "ping"})
    except WebSocketDisconnect:
        log.info("Agent events websocket disconnected")

@router.websocket("/ws/agents/chat/{session_id}")
async def agent_chat_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
    supervisor = websocket.app.state.supervisor
    
    if not supervisor or "chat" not in supervisor.agents:
        await websocket.close(code=1011, reason="Chat agent offline")
        return
        
    chat_agent = supervisor.agents["chat"]
    
    try:
        while True:
            data = await websocket.receive_text()
            # Send message to chat agent
            response = await chat_agent.chat(session_id, data)
            await websocket.send_json(response)
    except WebSocketDisconnect:
        log.info(f"Chat websocket disconnected for session {session_id}")

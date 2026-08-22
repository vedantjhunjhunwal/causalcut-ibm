from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from app.services.agent_service import AgentService, ChatMessage

router = APIRouter(prefix="/agent", tags=["agent"])

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    factory_id: str

class ChatResponse(BaseModel):
    response: str

# Singleton instance for now
_agent_service = AgentService()

@router.post("/chat", response_model=ChatResponse)
async def chat_with_agent(req: ChatRequest):
    try:
        response = await _agent_service.chat(req.messages)
        return ChatResponse(response=response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

"""Agent message bus for inter-agent communication."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.core.logging import get_logger
from app.db.session import Database

log = get_logger(__name__)


class AgentMessage(BaseModel):
    id: str
    timestamp: datetime
    sender: str
    recipient: str
    message_type: str
    priority: str
    payload: dict[str, Any]
    processed: bool = False


class MessageBus:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db
        self._queues: dict[str, asyncio.Queue] = {}
        self._history: list[AgentMessage] = []

    async def subscribe(self, agent_name: str) -> asyncio.Queue:
        if agent_name not in self._queues:
            self._queues[agent_name] = asyncio.Queue()
        return self._queues[agent_name]

    async def publish(self, message: AgentMessage | dict[str, Any]) -> None:
        if isinstance(message, dict):
            msg = AgentMessage(
                id=message.get("id") or str(uuid.uuid4()),
                timestamp=datetime.fromisoformat(message["timestamp"]) if "timestamp" in message and isinstance(message["timestamp"], str) else datetime.now(timezone.utc),
                sender=message.get("sender", "system"),
                recipient=message.get("recipient", message.get("topic", "*")),
                message_type=message.get("message_type") or message.get("topic", "General"),
                priority=message.get("priority", "NORMAL"),
                payload=message.get("payload", message),
            )
        else:
            msg = message

        self._history.append(msg)
        # Keep history bounded in memory for now
        if len(self._history) > 1000:
            self._history.pop(0)

        if msg.recipient == "*":
            for queue in self._queues.values():
                await queue.put(msg)
        else:
            queue = self._queues.get(msg.recipient)
            if queue:
                await queue.put(msg)
            else:
                # Also deliver to wildcard subscribers or topic subscribers
                delivered = False
                for name, q in self._queues.items():
                    if name in (msg.recipient, msg.message_type, "*"):
                        await q.put(msg)
                        delivered = True
                if not delivered:
                    log.warning(f"Recipient {msg.recipient} not found on bus.")

    async def get_pending(self, agent_name: str) -> list[AgentMessage]:
        if agent_name in ("ALL", "*"):
            pending = []
            for queue in self._queues.values():
                while not queue.empty():
                    try:
                        pending.append(queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
            return pending

        queue = self._queues.get(agent_name)
        if not queue:
            # Check if any messages in history match topic
            return []
        
        pending = []
        while not queue.empty():
            try:
                msg = queue.get_nowait()
                pending.append(msg)
            except asyncio.QueueEmpty:
                break
        return pending

    async def broadcast(
        self,
        sender: str,
        message_type: str,
        payload: dict[str, Any],
        priority: str = "NORMAL",
    ) -> None:
        msg = AgentMessage(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            sender=sender,
            recipient="*",
            message_type=message_type,
            priority=priority,
            payload=payload,
        )
        await self.publish(msg)

    async def get_recent_messages(self, limit: int = 50) -> list[AgentMessage]:
        return self._history[-limit:]

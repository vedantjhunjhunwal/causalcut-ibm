"""In-process async event queue (design doc §3.1).

MVP: asyncio.Queue. Production: PostgreSQL LISTEN/NOTIFY. The interface here is
deliberately narrow — put / get / stats — so that swap is a class replacement,
not a refactor. Explicitly *not* Kafka (Appendix B).

Backpressure policy: the queue is bounded. If it is full we do NOT block the
ingest request and we do NOT silently drop. The event is already durable in the
event store (we write before we queue), so a full queue degrades to
'persisted, awaiting replay' — which is the safe failure direction.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.schemas.canonical import SafetyEvent

log = get_logger(__name__)


@dataclass
class QueueCounters:
    enqueued: int = 0
    processed: int = 0
    failed: int = 0
    dead_lettered: int = 0
    rejected_full: int = 0
    retried: int = 0


@dataclass
class QueuedEvent:
    event: SafetyEvent
    attempt: int = 1


class EventQueue:
    def __init__(self, max_size: int = 10_000, put_timeout: float = 0.5) -> None:
        self._q: asyncio.Queue[QueuedEvent] = asyncio.Queue(maxsize=max_size)
        self.max_size = max_size
        self.put_timeout = put_timeout
        self.counters = QueueCounters()

    async def put(self, event: SafetyEvent, attempt: int = 1) -> bool:
        """False means backpressure, not data loss — the event store already
        holds the record."""
        try:
            await asyncio.wait_for(
                self._q.put(QueuedEvent(event, attempt)), timeout=self.put_timeout
            )
        except (asyncio.TimeoutError, asyncio.QueueFull):
            self.counters.rejected_full += 1
            log.warning(
                "event queue full; event persisted but not dispatched",
                extra={"event_id": str(event.event_id), "depth": self.depth},
            )
            return False
        self.counters.enqueued += 1
        return True

    async def get(self) -> QueuedEvent:
        return await self._q.get()

    def task_done(self) -> None:
        self._q.task_done()

    async def drain(self, timeout: float = 5.0) -> None:
        """Let consumers finish in-flight work on shutdown."""
        try:
            await asyncio.wait_for(self._q.join(), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("queue drain timed out", extra={"depth": self.depth})

    @property
    def depth(self) -> int:
        return self._q.qsize()

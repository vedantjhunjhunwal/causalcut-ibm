"""Scenario sessions — correlation-scoped graph state for user scenarios.

The live ``RiskEngine`` owns one long-lived Steelforge graph. A *user* scenario
needs its own graph, but must still travel the real ingestion spine:

    ingest -> event store -> asyncio queue -> consumer -> plant-state store
                                                 |
                                                 +-> scenario session graph

A session is registered before its events are ingested. The existing
``ConsumerPool`` — after it has durably projected each event into SQLite —
hands the event to the session whose ``correlation_id`` matches. The session
applies it to its own hypergraph and counts it, so the API can await genuine
pipeline completion rather than guessing with a sleep.

This adds a subscriber to the existing consumer; it does not duplicate the
queue, the projector or the state store.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from app.engine.hypergraph_wrapper import SafetyHypergraph
    from app.schemas.canonical import SafetyEvent

log = get_logger(__name__)


@dataclass
class ScenarioSession:
    """Tracks one scenario run as its events flow through the real pipeline."""

    correlation_id: str
    scenario_id: str
    graph: "SafetyHypergraph"
    expected: int = 0
    applied: int = 0
    skipped: int = 0
    seen: int = 0
    expected_set: bool = False
    errors: list[str] = field(default_factory=list)
    _done: asyncio.Event = field(default_factory=asyncio.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- consumer side ------------------------------------------------- #
    def apply(self, event: "SafetyEvent") -> None:
        """Called by the queue consumer after the durable projection."""
        from app.engine.adapter import canonical_to_engine

        try:
            engine_event = canonical_to_engine(event)
            with self._lock:
                if engine_event is not None:
                    self.graph.apply_event(engine_event)
                    self.applied += 1
                else:
                    self.skipped += 1
                self.seen += 1
                # Only completable once the API has declared how many events
                # it ingested; otherwise the first event would signal "done".
                complete = self.expected_set and self.seen >= self.expected
        except Exception as exc:  # never kill the consumer
            with self._lock:
                self.errors.append(str(exc))
                self.seen += 1
                complete = self.expected_set and self.seen >= self.expected
            log.warning("scenario session apply failed",
                        extra={"correlation_id": self.correlation_id, "error": str(exc)})

        if complete:
            self._done.set()

    # -- API side ------------------------------------------------------- #
    def set_expected(self, n: int) -> None:
        with self._lock:
            self.expected = n
            self.expected_set = True
            already_complete = self.seen >= n
        if already_complete:
            self._done.set()

    async def wait(self, timeout: float) -> bool:
        """Await full pipeline processing. Returns False on timeout."""
        if self.expected == 0:
            return True
        try:
            await asyncio.wait_for(self._done.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            log.warning("scenario pipeline wait timed out",
                        extra={"correlation_id": self.correlation_id,
                               "seen": self.seen, "expected": self.expected})
            return False

    def stats(self) -> dict:
        return {"expected": self.expected, "applied": self.applied,
                "skipped": self.skipped, "seen": self.seen,
                "errors": list(self.errors)}


class ScenarioSessionRegistry:
    """Thread-safe correlation_id -> session map consulted by the consumer."""

    def __init__(self) -> None:
        self._sessions: dict[str, ScenarioSession] = {}
        self._lock = threading.Lock()

    def register(self, session: ScenarioSession) -> None:
        with self._lock:
            self._sessions[session.correlation_id] = session

    def get(self, correlation_id: str | None) -> ScenarioSession | None:
        if not correlation_id:
            return None
        with self._lock:
            return self._sessions.get(correlation_id)

    def release(self, correlation_id: str) -> None:
        with self._lock:
            self._sessions.pop(correlation_id, None)

    @property
    def active(self) -> int:
        with self._lock:
            return len(self._sessions)


_registry = ScenarioSessionRegistry()


def get_session_registry() -> ScenarioSessionRegistry:
    return _registry

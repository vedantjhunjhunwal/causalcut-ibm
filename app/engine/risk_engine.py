"""Risk engine service — the analytical half of CAUSALCUT.

This is the module the ingestion spine's consumer docstring anticipated:
"[the projector] does NOT compute risk, activate hyperedges or select
interventions — those modules subscribe to the same queue later." This is
"later".

It maintains an in-memory ``SafetyHypergraph`` fed from the same canonical
events the ``StateProjector`` writes to SQLite, and on demand runs the full
pipeline:

    compound rules -> accident sub-pathways -> minimum causal cut

The engine only ever *recommends*. Dispatch/approval is the gateway's job.
"""

from __future__ import annotations

import threading
from typing import Any

from app.engine.adapter import canonical_to_engine
from app.engine.compound_rules import CompoundRuleEngine
from app.engine.cut_optimiser import CutRecommendation, MinimumCausalCutOptimiser
from app.engine.hypergraph_wrapper import SafetyHypergraph
from app.engine.path_extractor import AccidentPath, PathExtractor
from app.schemas.canonical import SafetyEvent as CanonicalEvent
from app.core.logging import get_logger

log = get_logger(__name__)


class RiskEngine:
    def __init__(self, safety_threshold: float = 0.15) -> None:
        self.graph = SafetyHypergraph()
        self.graph.bootstrap_steelforge()
        self.rules = CompoundRuleEngine(self.graph)
        self.extractor = PathExtractor(self.graph)
        self.optimiser = MinimumCausalCutOptimiser(safety_threshold)
        self._lock = threading.RLock()
        self._applied = 0
        self._last_paths: list[AccidentPath] = []
        self._last_rec: CutRecommendation | None = None
        self._dirty = True

    # ------------------------------------------------------------------ #
    def apply_canonical(self, event: CanonicalEvent) -> bool:
        """Feed one canonical event into the graph. Returns True if the engine
        recognised and applied it. Never raises on unhandled types."""
        engine_event = canonical_to_engine(event)
        if engine_event is None:
            return False
        with self._lock:
            self.graph.apply_event(engine_event)
            self._applied += 1
            self._dirty = True
        return True

    # ------------------------------------------------------------------ #
    def evaluate(self) -> tuple[list[AccidentPath], CutRecommendation | None]:
        """Run the full pipeline against the current graph state and cache it."""
        with self._lock:
            activated = self.rules.evaluate()
            paths = self.extractor.extract_all(activated)
            rec = self.optimiser.solve(paths) if paths else None
            self._last_paths, self._last_rec, self._dirty = paths, rec, False
            if rec is not None:
                log.info(
                    "risk evaluation",
                    extra={
                        "active_paths": len(paths),
                        "residual_risk": rec.residual_risk,
                        "threshold_met": rec.threshold_met,
                        "interventions": [i.intervention_id for i in rec.interventions],
                    },
                )
            return paths, rec

    def current(self) -> tuple[list[AccidentPath], CutRecommendation | None]:
        """Cached view; re-evaluates only if new events arrived since last run."""
        if self._dirty:
            return self.evaluate()
        return self._last_paths, self._last_rec

    # ------------------------------------------------------------------ #
    def paths_payload(self) -> dict[str, Any]:
        paths, _ = self.current()
        return {
            "active_paths": [p.to_dict() for p in paths],
            "count": len(paths),
            "graph_revision": self.graph.revision,
        }

    def recommendation_payload(self) -> dict[str, Any]:
        _, rec = self.current()
        return {
            "recommendation": rec.to_dict() if rec else None,
            "graph_revision": self.graph.revision,
            "events_applied": self._applied,
        }

    def stats(self) -> dict[str, Any]:
        return {
            "events_applied": self._applied,
            "graph_revision": self.graph.revision,
            "safety_threshold": self.optimiser.safety_threshold,
        }

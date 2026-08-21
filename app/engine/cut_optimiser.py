"""Minimum-causal-cut optimiser.

Given the accident paths currently active (each a set of contributing factors)
and the candidate interventions (each breaking a subset of factors at some
cost), find the smallest / cheapest set of interventions that breaks every
critical factor and pushes residual risk below the safety threshold.

This is the weighted set-cover formulation from design doc section 6, solved
with OR-Tools CP-SAT. If OR-Tools is unavailable we fall back to a greedy
set-cover so the system still produces a (non-optimal but safe) recommendation.

The optimiser is stateless and pure: it computes a recommendation. Nothing is
executed. Human approval is enforced downstream by the gateway.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.engine.path_extractor import AccidentPath, CandidateIntervention
from app.engine.types import InformationClass

logger = logging.getLogger("causalcut.optimiser")

try:
    from ortools.sat.python import cp_model
    _HAS_ORTOOLS = True
except Exception:  # pragma: no cover - fallback path
    _HAS_ORTOOLS = False


# Cost/disruption category -> integer weight (CP-SAT needs integers).
_COST = {"LOW": 1, "MEDIUM": 4, "HIGH": 12}
_DISRUPTION = {"MINIMAL": 1, "LOW": 2, "MEDIUM": 5, "HIGH": 12}

# Default objective weights (design doc 6.2).
W_COST = 1
W_DISRUPTION = 2
W_LATENCY = 1
W_CARDINALITY = 4


@dataclass
class CutRecommendation:
    interventions: list[CandidateIntervention]
    residual_risk: float
    safety_threshold: float
    threshold_met: bool
    covered_factors: set[str]
    total_cost_category: str
    pathways_broken: list[str]
    rejected_alternatives: list[str] = field(default_factory=list)
    info_class: InformationClass = InformationClass.COUNTERFACTUAL
    solver: str = "cp-sat"

    def to_dict(self) -> dict:
        return {
            "interventions": [
                {
                    "intervention_id": c.intervention_id,
                    "intervention_type": c.intervention_type,
                    "priority": i + 1,
                    "action": c.action,
                    "cost_category": c.cost_category,
                    "disruption": c.disruption,
                    "execution_time_min": c.execution_time_min,
                    "breaks_factors": sorted(c.breaks_factors),
                }
                for i, c in enumerate(self.interventions)
            ],
            "residual_risk": round(self.residual_risk, 3),
            "safety_threshold": self.safety_threshold,
            "threshold_met": self.threshold_met,
            "covered_factors": sorted(self.covered_factors),
            "total_cost": self.total_cost_category,
            "pathways_broken": self.pathways_broken,
            "info_class": self.info_class.value,
            "solver": self.solver,
        }


class MinimumCausalCutOptimiser:
    def __init__(self, safety_threshold: float = 0.15) -> None:
        self.safety_threshold = safety_threshold

    # ------------------------------------------------------------------ #
    def solve(self, paths: list[AccidentPath]) -> Optional[CutRecommendation]:
        if not paths:
            return None

        # Enumerate every live accident sub-pathway across all active paths.
        # Each sub-pathway is a conjunction of necessary factors; breaking any
        # one necessary factor breaks that route (hitting-set formulation).
        sub_pathways = []  # list of (path_key, necessary_factors)
        for p in paths:
            for sp in p.sub_pathways:
                sub_pathways.append((f"{p.hyperedge_id}:{sp.name}", sp.necessary_factors))

        # Deduplicate interventions by id across paths, unioning their coverage.
        catalogue: dict[str, CandidateIntervention] = {}
        for p in paths:
            for c in p.candidate_interventions:
                if c.intervention_id in catalogue:
                    catalogue[c.intervention_id].breaks_factors |= c.breaks_factors
                else:
                    catalogue[c.intervention_id] = c
        candidates = list(catalogue.values())

        # Coverage matrix: intervention breaks a sub-pathway iff it removes at
        # least one of that route's necessary factors.
        def breaks(cand: CandidateIntervention, necessary: frozenset[str]) -> bool:
            return bool(cand.breaks_factors & necessary)

        base_severity = max(p.severity for p in paths)

        if _HAS_ORTOOLS:
            chosen = self._solve_cp_sat(sub_pathways, candidates, breaks)
            solver_name = "cp-sat"
        else:
            chosen = self._solve_greedy(sub_pathways, candidates, breaks)
            solver_name = "greedy-fallback"

        if chosen is None:
            logger.warning("optimiser found no feasible cut; recommending zone closure")
            chosen = self._emergency_closure(candidates)
            solver_name = "emergency-fallback"

        covered = set().union(*(c.breaks_factors for c in chosen)) if chosen else set()
        residual = self._residual_risk(base_severity, sub_pathways, chosen, breaks)

        return CutRecommendation(
            interventions=sorted(chosen, key=lambda c: (_COST[c.cost_category], c.execution_time_min)),
            residual_risk=residual,
            safety_threshold=self.safety_threshold,
            threshold_met=residual <= self.safety_threshold,
            covered_factors=covered,
            total_cost_category=self._aggregate_cost(chosen),
            pathways_broken=sorted({p.pathway for p in paths}),
            solver=solver_name,
        )

    # ------------------------------------------------------------------ #
    def _weight(self, c: CandidateIntervention) -> int:
        return (
            W_COST * _COST[c.cost_category]
            + W_DISRUPTION * _DISRUPTION[c.disruption]
            + W_LATENCY * int(round(c.execution_time_min))
            + W_CARDINALITY
        )

    def _solve_cp_sat(
        self,
        sub_pathways: list[tuple[str, frozenset[str]]],
        candidates: list[CandidateIntervention],
        breaks,
    ) -> Optional[list[CandidateIntervention]]:
        model = cp_model.CpModel()
        x = {c.intervention_id: model.NewBoolVar(c.intervention_id) for c in candidates}

        # Constraint 1 (design doc 6.1): every accident sub-pathway must be
        # broken by at least one selected intervention.
        for key, necessary in sub_pathways:
            coverers = [x[c.intervention_id] for c in candidates if breaks(c, necessary)]
            if not coverers:
                logger.error("sub-pathway %s has no covering intervention -- infeasible", key)
                return None
            model.Add(sum(coverers) >= 1)

        # Objective (design doc 6.2): weighted cost + disruption + latency +
        # cardinality, strongly preferring fewer, cheaper interventions.
        model.Minimize(sum(self._weight(c) * x[c.intervention_id] for c in candidates))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 2.0
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        return [c for c in candidates if solver.Value(x[c.intervention_id]) == 1]

    def _solve_greedy(
        self,
        sub_pathways: list[tuple[str, frozenset[str]]],
        candidates: list[CandidateIntervention],
        breaks,
    ) -> Optional[list[CandidateIntervention]]:
        uncovered = list(sub_pathways)
        chosen: list[CandidateIntervention] = []
        pool = list(candidates)
        while uncovered:
            best = None
            best_score = -1.0
            for c in pool:
                gain = sum(1 for _, nec in uncovered if breaks(c, nec))
                if gain == 0:
                    continue
                score = gain / self._weight(c)
                if score > best_score:
                    best, best_score = c, score
            if best is None:
                return None
            chosen.append(best)
            uncovered = [(k, nec) for (k, nec) in uncovered if not breaks(best, nec)]
            pool.remove(best)
        return chosen

    def _emergency_closure(self, candidates: list[CandidateIntervention]) -> list[CandidateIntervention]:
        closures = [c for c in candidates if c.intervention_type == "close_zone"]
        return closures[:1] if closures else candidates[:1]

    # ------------------------------------------------------------------ #
    def _residual_risk(
        self,
        base: float,
        sub_pathways: list[tuple[str, frozenset[str]]],
        chosen: list[CandidateIntervention],
        breaks,
    ) -> float:
        """Residual risk = base severity scaled by the fraction of accident
        routes still open plus a hazard-source penalty.

        A route counts as broken if any chosen intervention removes one of its
        necessary factors. Even with every route combinatorially broken, a
        residual is kept for any active hazard sources (gas/ignition) still in
        the plant, because they can seed new routes (propagation, other
        workers) -- which is why protecting one worker is never enough on its
        own.
        """
        if not sub_pathways:
            return 0.0
        open_routes = 0
        remaining_hazard: set[str] = set()
        hazard_sources = {"gas_source", "ignition_source", "equipment_hazard", "ventilation_deficit", "unprotected_worker"}
        covered = set().union(*(c.breaks_factors for c in chosen)) if chosen else set()

        for _, necessary in sub_pathways:
            if not any(breaks(c, necessary) for c in chosen):
                open_routes += 1
            remaining_hazard |= (necessary & hazard_sources) - covered

        open_fraction = open_routes / len(sub_pathways)
        # total distinct hazard sources across all routes
        all_hazard = set().union(*(nec & hazard_sources for _, nec in sub_pathways)) or {"_"}
        hazard_fraction = len(remaining_hazard) / len(all_hazard)

        residual = base * (0.8 * open_fraction + 0.2 * hazard_fraction)
        return round(residual, 3)

    def _aggregate_cost(self, chosen: list[CandidateIntervention]) -> str:
        if not chosen:
            return "NONE"
        worst = max(_COST[c.cost_category] for c in chosen)
        for name, val in _COST.items():
            if val == worst:
                return name
        return "LOW"

"""Minimum-Causal-Cut optimiser (design doc ï¿½6, ï¿½F). Owner: Riya.

Weighted set cover, solved with CP-SAT:
    minimise   sum_c cost_c * choose_c
    subject to sum_{c: path in covers(c)} choose_c >= 1   per active path
               choose_a + choose_b <= 1                    per incompatible pair
               choose_c == 0                                if latency_c > max_latency_s

cost_c is expected to already fold residual risk / exposure / disruption /
uncertainty into one 0-1 number before it reaches here (that reduction is
CounterfactualSimulator.risk_reduction() plus cost weighting) -- this file
only does the combinatorial selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class CandidateIntervention:
    id: str
    action: str
    cost: float
    latency_s: float
    covers_paths: frozenset[str]
    incompatible_with: frozenset[str] = field(default_factory=frozenset)
    required_approver: str = "safety_supervisor"


@dataclass
class CausalCutResult:
    chosen_ids: list[str]
    uncovered_paths: frozenset[str]
    status: str  # "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "NO_CANDIDATES"


def solve_minimum_causal_cut(
    candidates: list[CandidateIntervention],
    active_paths: set[str],
    max_latency_s: float | None = None,
) -> CausalCutResult:
    if not candidates:
        return CausalCutResult([], frozenset(active_paths), "NO_CANDIDATES")

    coverable_paths = {p for p in active_paths if any(p in c.covers_paths for c in candidates)}
    uncovered = frozenset(active_paths - coverable_paths)
    if not coverable_paths:
        return CausalCutResult([], uncovered, "INFEASIBLE")

    model = cp_model.CpModel()
    choose = {c.id: model.NewBoolVar(f"choose_{c.id}") for c in candidates}

    for path in coverable_paths:
        model.Add(sum(choose[c.id] for c in candidates if path in c.covers_paths) >= 1)

    for c in candidates:
        for other_id in c.incompatible_with:
            if other_id in choose:
                model.Add(choose[c.id] + choose[other_id] <= 1)

    if max_latency_s is not None:
        for c in candidates:
            if c.latency_s > max_latency_s:
                model.Add(choose[c.id] == 0)

    model.Minimize(sum(round(c.cost * 1000) * choose[c.id] for c in candidates))

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return CausalCutResult([], frozenset(active_paths), "INFEASIBLE")

    chosen_ids = [c.id for c in candidates if solver.Value(choose[c.id]) == 1]
    return CausalCutResult(chosen_ids, uncovered, "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE")


if __name__ == "__main__":
    candidates = [
        CandidateIntervention("close_ventilation_barrier", "isolate_equipment", 0.15, 30, frozenset({"HE-042"})),
        CandidateIntervention("suspend_hot_work_permit", "suspend_permit", 0.10, 10, frozenset({"HE-042"})),
        CandidateIntervention("evacuate_zone_1", "evacuate_workers", 0.60, 120, frozenset({"HE-042"}),
                               incompatible_with=frozenset({"suspend_hot_work_permit"})),
    ]
    result = solve_minimum_causal_cut(candidates, active_paths={"HE-042"})
    print(f"status: {result.status}  chosen: {result.chosen_ids}  uncovered: {set(result.uncovered_paths)}")


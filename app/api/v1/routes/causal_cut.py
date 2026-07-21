"""Minimum-Causal-Cut recommendation + counterfactual simulation endpoints.

MERGE NOTE (read this first):
This file merges two things that were built independently and both work:

  * Riya's standalone risk_propagator / counterfactual_sim / causal_cut_solver
    pipeline (this file, originally self-contained so it was runnable before
    the hypergraph existed).
  * Vedant/Tarun's real hypergraph pipeline: SafetyHypergraph -> CompoundRuleEngine
    -> PathExtractor -> MinimumCausalCutOptimiser, wired into `RiskEngine` and
    exposed at /risk/paths, /risk/recommendation, /risk/approve (with real auth
    + hash-chained audit log). That is the system of record for "what's the
    current recommendation" and "who approved it" -- keep using /risk/* for that.

What THIS file still owns and is not duplicated anywhere else:
  * /causal-cut/simulate -- baseline-vs-intervention risk trajectories over time
    (the SimPy/Euler-diffusion "what if we close this barrier" chart). Nothing
    in the hypergraph branch computes a time series, only a point-in-time cut.
  * /causal-cut/recommend -- kept as a standalone/testable endpoint (useful in
    CI and for the dashboard's demo mode when risk_engine isn't mounted), but
    when `app.state.risk_engine` IS mounted, it now seeds zone_risk /
    hazard_severity from the LIVE graph instead of trusting the request body,
    so it stops being a toy and starts reflecting real plant state.

If you're merging this into main.py: this router still only needs
`request.app.state.risk_engine` to be *optional*. Nothing here breaks if it's
absent (tests and local dev without the full engine still work).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.engine.risk_propagator import PropagationInputs, estimate_time_to_harm
from app.optimizer.causal_cut_solver import CandidateIntervention, CausalCutResult, solve_minimum_causal_cut
from app.simulation.counterfactual_sim import CounterfactualSimulator, Intervention

router = APIRouter(prefix="/causal-cut", tags=["causal-cut"])


_PPM_SEVERITY_SATURATION = 300.0


def _live_zone_state(request: Request) -> tuple[dict[str, float], dict[str, float]] | None:
    """Read (zone_risk, hazard_severity) off the live SafetyHypergraph.

    Returns None if no risk_engine is mounted on this app (standalone/test
    mode) so callers can fall back to request-body values.
    """
    risk_engine = getattr(request.app.state, "risk_engine", None)
    if risk_engine is None:
        return None

    graph = risk_engine.graph
    hazard_severity: dict[str, float] = {}
    zone_risk: dict[str, float] = {}

    for zone_id in graph.nodes_of_type_zone():
        node = graph.node(zone_id)
        ppm = node.get("last_gas_ppm") or 0.0
        severity = max(0.0, min(1.0, ppm / _PPM_SEVERITY_SATURATION))
        hazard_severity[zone_id] = severity
        zone_risk[zone_id] = severity

    return zone_risk, hazard_severity


class CandidateActionIn(BaseModel):
    id: str
    action: str
    cost: float = Field(ge=0.0, le=1.0)
    latency_s: float = Field(ge=0.0)
    covers_paths: list[str]
    incompatible_with: list[str] = []


class CausalCutRequest(BaseModel):
    zone_risk: dict[str, float] = Field(default_factory=dict)
    hazard_severity: dict[str, float] = Field(default_factory=dict)
    active_paths: list[str] = Field(default_factory=list)
    candidates: list[CandidateActionIn] = Field(default_factory=list)
    watch_zone: str
    max_latency_s: float | None = None
    harm_threshold: float = 0.75
    use_live_graph: bool = True


class CausalCutResponse(BaseModel):
    information_class: str = "P"
    status: str
    recommended_action_ids: list[str]
    uncovered_paths: list[str]
    time_to_harm_seconds: float | None
    source: str = "standalone"
    requires_human_approval: bool = True
    note: str = (
        "This is a recommendation only. No action executes without explicit "
        "human approval via POST /api/v1/risk/approve."
    )


class SimulateRequest(BaseModel):
    zone_risk: dict[str, float] = Field(default_factory=dict)
    hazard_severity: dict[str, float] = Field(default_factory=dict)
    horizon_seconds: float = 300.0
    dt_seconds: float = 10.0
    close_barrier_edge: tuple[str, str] | None = None
    close_barrier_at_s: float = 0.0
    close_barrier_magnitude: float = 0.05
    use_live_graph: bool = True


class SimulateResponse(BaseModel):
    information_class: str = "P"
    timestamps_s: list[float]
    baseline: dict[str, list[float]]
    treated: dict[str, list[float]] | None = None
    source: str = "standalone"


@router.post("/recommend", response_model=CausalCutResponse, summary="Minimum-causal-cut recommendation")
async def recommend(req: CausalCutRequest, request: Request) -> CausalCutResponse:
    source = "standalone"
    zone_risk, hazard_severity = req.zone_risk, req.hazard_severity

    if req.use_live_graph:
        live = _live_zone_state(request)
        if live is not None:
            zone_risk, hazard_severity = live
            source = "live_graph"

    prop_inputs = PropagationInputs(risk=zone_risk, hazard_severity=hazard_severity, barrier_multiplier={})
    time_to_harm = estimate_time_to_harm(prop_inputs, zone=req.watch_zone, threshold=req.harm_threshold)

    candidates = [
        CandidateIntervention(c.id, c.action, c.cost, c.latency_s,
                               frozenset(c.covers_paths), frozenset(c.incompatible_with))
        for c in req.candidates
    ]
    cut_result: CausalCutResult = solve_minimum_causal_cut(
        candidates, active_paths=set(req.active_paths), max_latency_s=req.max_latency_s
    )
    return CausalCutResponse(
        status=cut_result.status,
        recommended_action_ids=cut_result.chosen_ids,
        uncovered_paths=sorted(cut_result.uncovered_paths),
        time_to_harm_seconds=time_to_harm,
        source=source,
    )


@router.post("/simulate", response_model=SimulateResponse, summary="Baseline vs. treated risk trajectories")
async def simulate(req: SimulateRequest, request: Request) -> SimulateResponse:
    source = "standalone"
    zone_risk, hazard_severity = req.zone_risk, req.hazard_severity

    if req.use_live_graph:
        live = _live_zone_state(request)
        if live is not None:
            zone_risk, hazard_severity = live
            source = "live_graph"

    prop_inputs = PropagationInputs(risk=zone_risk, hazard_severity=hazard_severity, barrier_multiplier={})
    sim = CounterfactualSimulator(prop_inputs, dt_seconds=req.dt_seconds, horizon_seconds=req.horizon_seconds)
    baseline = sim.run_baseline()

    zones = sorted({z for snap in baseline.trajectory for z in snap})
    baseline_series = {z: [snap.get(z, 0.0) for snap in baseline.trajectory] for z in zones}

    treated_series = None
    if req.close_barrier_edge is not None:
        treated = sim.run_with_interventions([
            Intervention(time_s=req.close_barrier_at_s, action="close_barrier",
                         target=req.close_barrier_edge, magnitude=req.close_barrier_magnitude)
        ])
        treated_series = {z: [snap.get(z, 0.0) for snap in treated.trajectory] for z in zones}

    return SimulateResponse(
        timestamps_s=baseline.timestamps_s,
        baseline=baseline_series,
        treated=treated_series,
        source=source,
    )

"""Spatiotemporal risk propagation â€” Day 1 math spec + reference implementation.

Design doc Â§5 (Risk Evaluation & Propagation Logic) / Â§8 coke-oven scenario.
Owner: Riya.

--------------------------------------------------------------------------
MATH SPEC
--------------------------------------------------------------------------
Each zone i carries a scalar risk level R_i(t) in [0, 1]. Risk is injected
by local hazard events (gas anomaly severity, equipment failure severity â€”
[P]/[M] from the canonical event stream) and diffuses to neighbouring zones
through the topology graph, decaying over time as ventilation/isolation
removes the hazard.

Discrete-time update (Euler step, dt in seconds), for every zone i:

    R_i(t+dt) = clamp01(
        R_i(t)
        - decay_i * R_i(t) * dt                                    # local dissipation
        + dt * sum_j  COUPLING_RATE * w_ij * B_ij(t) * (R_j(t)-R_i(t))  # diffusion
        + S_i(t)                                                    # injected hazard
    )

Where:
    decay_i        zone-specific dissipation rate (1/s).
    w_ij           static topology edge weight (0-1), from topology.py.
    COUPLING_RATE   global 1/s constant scaling how fast hazard equalises
                    across a fully-open edge â€” kept separate from w_ij so
                    the Euler step stays stable at coarse dt (see note by
                    the constant below).
    B_ij(t)        barrier multiplier in [0,1]. 1.0 = barrier open/failed,
                    0.0 = fully closed. Defaults to 1.0 (open) when
                    unknown â€” fail-open on the propagation model is a
                    deliberately pessimistic assumption, because
                    understating spread is the unsafe direction of error.
    S_i(t)         injected hazard = max(0, 1-R_i(t)) * max(severity_e for
                    e in active_events(zone=i, t)) â€” max, not sum, so one
                    dominant hazard isn't diluted by unrelated minor events.

This is a [P]-class output once wired to live events, and every propagated
value must carry the zone(s)/event(s) it traces to â€” that's what lets the
optimiser later explain "why" a zone is at 0.7.

TIME-TO-HARM
    First t* such that R_i(t*) >= theta (default 0.75), found by
    forward-simulating this rule under a "no new intervention" assumption.
    If R_i is already decaying below theta, time-to-harm is None ("not
    currently on a harm trajectory") â€” never a fabricated large number.

WHAT DAY 1 DELIVERS: this module + topology.py + the SimPy scaffold, all
runnable standalone on plain dicts, no DB/queue wiring yet.

DEFERRED: reading live severity/barrier state from the event store (Day 2),
compound-hyperedge-aware injection (Day 5), calibrating decay_i/theta
against OSHA priors (Day 4).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.topology import build_topology_graph
from app.schemas.enums import ZoneId

DEFAULT_HARM_THRESHOLD = 0.75

# How fast hazard equalises across a *fully open* (w_ij=1.0) edge, in 1/s.
# Kept separate from w_ij so the Euler step stays stable at coarse dt --
# without it, a high-weight edge combined with dt=10s+ overshoots and
# oscillates between 0 and 1 instead of smoothly equalising. Rule of thumb:
# dt_seconds * DEFAULT_COUPLING_RATE < 0.2.
DEFAULT_COUPLING_RATE = 0.02

# Placeholder per-zone dissipation rates (1/s). [S] estimate â€” replace with
# calibrated values once real ventilation response data exists.
DEFAULT_DECAY_RATES: dict[str, float] = {
    ZoneId.ZONE_1_COKE_OVEN.value: 0.004,
    ZoneId.ZONE_2_BLAST_FURNACE.value: 0.005,
    ZoneId.ZONE_3_MACHINE_SHOP.value: 0.010,
    ZoneId.ZONE_4_SHARED_UTILITIES.value: 0.015,  # extraction fans live here
    ZoneId.ZONE_5_CCTV_CHECKPOINTS.value: 0.020,
    ZoneId.ZONE_6_CONTROL_ROOM.value: 0.020,
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class PropagationInputs:
    """One time-step's worth of inputs, already reduced from raw events."""

    risk: dict[str, float]                # zone_id -> R_i(t)
    hazard_severity: dict[str, float]     # zone_id -> max active severity
    barrier_multiplier: dict[str, float]  # sorted (zone_a, zone_b) -> B_ij, default 1.0


def propagate_step(
    inputs: PropagationInputs,
    dt_seconds: float = 5.0,
    decay_rates: dict[str, float] | None = None,
    graph=None,
) -> dict[str, float]:
    """One Euler step of the diffusion update above. Pure function, no I/O."""
    graph = graph or build_topology_graph()
    decay_rates = decay_rates or DEFAULT_DECAY_RATES

    risk = inputs.risk
    next_risk: dict[str, float] = {}

    for zone in graph.nodes:
        r_i = risk.get(zone, 0.0)
        decay_i = decay_rates.get(zone, 0.01)

        diffusion = 0.0
        for neighbour in graph.neighbors(zone):
            w_ij = graph[zone][neighbour]["weight"]
            edge_key = tuple(sorted((zone, neighbour)))
            b_ij = inputs.barrier_multiplier.get(edge_key, 1.0)
            r_j = risk.get(neighbour, 0.0)
            diffusion += DEFAULT_COUPLING_RATE * w_ij * b_ij * (r_j - r_i)

        severity = inputs.hazard_severity.get(zone, 0.0)
        injected = max(0.0, 1.0 - r_i) * severity * 0.03 * dt_seconds

        r_next = r_i - decay_i * r_i * dt_seconds + dt_seconds * diffusion + injected
        next_risk[zone] = _clamp01(r_next)

    return next_risk


def estimate_time_to_harm(
    initial_inputs: PropagationInputs,
    zone: str,
    threshold: float = DEFAULT_HARM_THRESHOLD,
    dt_seconds: float = 5.0,
    max_horizon_seconds: float = 1800.0,
    decay_rates: dict[str, float] | None = None,
    graph=None,
) -> float | None:
    """Forward-simulate under 'no new intervention' until `zone` crosses
    `threshold`, or `max_horizon_seconds` elapses. None if it never crosses.
    """
    graph = graph or build_topology_graph()
    risk = dict(initial_inputs.risk)
    elapsed = 0.0

    if risk.get(zone, 0.0) >= threshold:
        return 0.0

    while elapsed < max_horizon_seconds:
        step_inputs = PropagationInputs(
            risk=risk,
            hazard_severity=initial_inputs.hazard_severity,
            barrier_multiplier=initial_inputs.barrier_multiplier,
        )
        risk = propagate_step(step_inputs, dt_seconds=dt_seconds, decay_rates=decay_rates, graph=graph)
        elapsed += dt_seconds
        if risk.get(zone, 0.0) >= threshold:
            return elapsed

    return None

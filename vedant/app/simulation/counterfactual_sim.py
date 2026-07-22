"""Counterfactual simulator (design doc ï¿½F, ï¿½8). Owner: Riya.

run_baseline() = "do nothing" trajectory.
run_with_interventions(...) = same physics, with actions applied mid-run by
mutating a *local copy* of barrier_multiplier / decay_rates -- the original
initial_inputs never changes, so one simulator instance can score many
candidate action sets against the same baseline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import simpy

from app.engine.risk_propagator import DEFAULT_DECAY_RATES, PropagationInputs, propagate_step
from app.engine.topology import build_topology_graph


@dataclass
class SimulationResult:
    trajectory: list[dict[str, float]] = field(default_factory=list)
    timestamps_s: list[float] = field(default_factory=list)

    def final_risk(self, zone: str) -> float:
        return self.trajectory[-1].get(zone, 0.0) if self.trajectory else 0.0

    def peak_risk(self, zone: str) -> float:
        return max((snap.get(zone, 0.0) for snap in self.trajectory), default=0.0)


@dataclass(frozen=True)
class Intervention:
    """action: "close_barrier" (target=(zone_a,zone_b), magnitude=resulting
    B_ij) or "boost_ventilation" (target=zone_id, magnitude=decay
    multiplier). Other design-doc actions (evacuate, PPE, permits) reduce
    *exposure* not physical risk -- folded in once the optimiser scores
    exposure alongside residual risk, not here."""

    time_s: float
    action: str
    target: tuple[str, str] | str
    magnitude: float = 0.0


class CounterfactualSimulator:
    def __init__(
        self,
        initial_inputs: PropagationInputs,
        dt_seconds: float = 5.0,
        horizon_seconds: float = 900.0,
        graph=None,
        decay_rates: dict[str, float] | None = None,
    ) -> None:
        self.initial_inputs = initial_inputs
        self.dt_seconds = dt_seconds
        self.horizon_seconds = horizon_seconds
        self.graph = graph or build_topology_graph()
        self.decay_rates = dict(decay_rates or DEFAULT_DECAY_RATES)

    def _run(self, interventions: list[Intervention]) -> SimulationResult:
        result = SimulationResult()
        env = simpy.Environment()

        barrier_multiplier = dict(self.initial_inputs.barrier_multiplier)
        decay_rates = dict(self.decay_rates)
        pending = sorted(interventions, key=lambda iv: iv.time_s)

        def clock(env: simpy.Environment):
            nonlocal barrier_multiplier, decay_rates
            risk = dict(self.initial_inputs.risk)
            applied = 0
            while env.now < self.horizon_seconds:
                while applied < len(pending) and pending[applied].time_s <= env.now:
                    iv = pending[applied]
                    if iv.action == "close_barrier":
                        edge_key = tuple(sorted(iv.target))
                        barrier_multiplier[edge_key] = iv.magnitude
                    elif iv.action == "boost_ventilation":
                        base = DEFAULT_DECAY_RATES.get(iv.target, 0.01)
                        decay_rates[iv.target] = base * iv.magnitude
                    applied += 1

                result.trajectory.append(dict(risk))
                result.timestamps_s.append(env.now)

                step_inputs = PropagationInputs(
                    risk=risk,
                    hazard_severity=self.initial_inputs.hazard_severity,
                    barrier_multiplier=barrier_multiplier,
                )
                risk = propagate_step(
                    step_inputs, dt_seconds=self.dt_seconds,
                    decay_rates=decay_rates, graph=self.graph,
                )
                yield env.timeout(self.dt_seconds)

        env.process(clock(env))
        env.run(until=self.horizon_seconds)
        return result

    def run_baseline(self) -> SimulationResult:
        return self._run(interventions=[])

    def run_with_interventions(self, interventions: list[Intervention]) -> SimulationResult:
        return self._run(interventions=interventions)

    @staticmethod
    def risk_reduction(baseline: SimulationResult, treated: SimulationResult, zone: str) -> float:
        return baseline.peak_risk(zone) - treated.peak_risk(zone)


if __name__ == "__main__":
    from app.schemas.enums import ZoneId

    demo_inputs = PropagationInputs(
        risk={ZoneId.ZONE_1_COKE_OVEN.value: 0.55},
        hazard_severity={ZoneId.ZONE_1_COKE_OVEN.value: 0.8},
        barrier_multiplier={},
    )
    sim = CounterfactualSimulator(demo_inputs, dt_seconds=10.0, horizon_seconds=120.0)
    baseline = sim.run_baseline()
    treated = sim.run_with_interventions([
        Intervention(time_s=20.0, action="close_barrier",
                     target=(ZoneId.ZONE_1_COKE_OVEN.value, ZoneId.ZONE_4_SHARED_UTILITIES.value),
                     magnitude=0.05)
    ])
    reduction = CounterfactualSimulator.risk_reduction(baseline, treated, ZoneId.ZONE_4_SHARED_UTILITIES.value)
    print(f"peak risk reduction in zone-4: {reduction:.3f}")


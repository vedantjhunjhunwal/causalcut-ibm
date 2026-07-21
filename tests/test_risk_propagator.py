import pytest

from app.engine.risk_propagator import PropagationInputs, estimate_time_to_harm, propagate_step
from app.engine.topology import build_topology_graph
from app.schemas.enums import ZoneId
from app.simulation.counterfactual_sim import CounterfactualSimulator, Intervention

Z1 = ZoneId.ZONE_1_COKE_OVEN.value
Z4 = ZoneId.ZONE_4_SHARED_UTILITIES.value


def test_propagate_step_stays_in_bounds():
    inputs = PropagationInputs(risk={Z1: 0.9}, hazard_severity={Z1: 1.0}, barrier_multiplier={})
    for _ in range(50):
        next_risk = propagate_step(inputs, dt_seconds=5.0)
        assert all(0.0 <= v <= 1.0 for v in next_risk.values())
        inputs = PropagationInputs(risk=next_risk, hazard_severity=inputs.hazard_severity,
                                    barrier_multiplier=inputs.barrier_multiplier)


def test_risk_diffuses_to_neighbour():
    inputs = PropagationInputs(risk={Z1: 0.8}, hazard_severity={}, barrier_multiplier={})
    result = propagate_step(inputs, dt_seconds=10.0)
    assert result[Z4] > 0.0


def test_closed_barrier_blocks_diffusion():
    edge_key = tuple(sorted((Z1, Z4)))
    inputs = PropagationInputs(risk={Z1: 0.8}, hazard_severity={}, barrier_multiplier={edge_key: 0.0})
    result = propagate_step(inputs, dt_seconds=10.0)
    assert result[Z4] == pytest.approx(0.0)


def test_time_to_harm_none_when_not_on_harm_trajectory():
    inputs = PropagationInputs(risk={Z1: 0.1}, hazard_severity={}, barrier_multiplier={})
    assert estimate_time_to_harm(inputs, zone=Z1, threshold=0.75, max_horizon_seconds=300) is None


def test_time_to_harm_positive_under_sustained_hazard():
    inputs = PropagationInputs(risk={Z1: 0.1}, hazard_severity={Z1: 0.9}, barrier_multiplier={})
    tth = estimate_time_to_harm(inputs, zone=Z1, threshold=0.75, max_horizon_seconds=600)
    assert tth is not None and tth > 0


def test_intervention_reduces_downstream_peak_risk():
    inputs = PropagationInputs(risk={Z1: 0.55}, hazard_severity={Z1: 0.8}, barrier_multiplier={})
    sim = CounterfactualSimulator(inputs, dt_seconds=10.0, horizon_seconds=120.0)
    baseline = sim.run_baseline()
    treated = sim.run_with_interventions([
        Intervention(time_s=20.0, action="close_barrier", target=(Z1, Z4), magnitude=0.05)
    ])
    assert treated.peak_risk(Z4) < baseline.peak_risk(Z4)
    assert CounterfactualSimulator.risk_reduction(baseline, treated, Z4) > 0


def test_baseline_run_is_independent_of_prior_runs():
    inputs = PropagationInputs(risk={Z1: 0.55}, hazard_severity={Z1: 0.8}, barrier_multiplier={})
    sim = CounterfactualSimulator(inputs, dt_seconds=10.0, horizon_seconds=60.0)
    first = sim.run_baseline()
    sim.run_with_interventions([Intervention(time_s=10.0, action="close_barrier", target=(Z1, Z4), magnitude=0.0)])
    second = sim.run_baseline()
    assert first.trajectory == second.trajectory


def test_topology_graph_has_all_six_zones():
    assert build_topology_graph().number_of_nodes() == len(list(ZoneId))


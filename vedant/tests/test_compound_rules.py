"""Tests for the compound rule engine, path extractor and cut optimiser."""

from app.engine.compound_rules import CompoundRuleEngine
from app.engine.cut_optimiser import MinimumCausalCutOptimiser
from app.engine.hypergraph_wrapper import SafetyHypergraph
from app.engine.path_extractor import PathExtractor
from app.engine.types import EventType, InformationClass, SafetyEvent


def build_flashfire_graph() -> SafetyHypergraph:
    """Drive the graph into the HE-042 flash-fire condition."""
    g = SafetyHypergraph()
    g.bootstrap_steelforge()
    g.register_worker("W-003", "zone-1")
    g.register_permit("PTW-007", "zone-1", "hot_work", "active", "W-003")

    events = [
        SafetyEvent(event_type=EventType.GAS_ANOMALY, zone_id="zone-1",
                    sensor_id="GS-03", value={"gas_type": "ammonia", "concentration_ppm": 215.0},
                    information_class=InformationClass.MEASURED),
        SafetyEvent(event_type=EventType.PPE_VIOLATION, zone_id="zone-1",
                    worker_id="W-003", value={"missing_ppe": ["hard_hat"]},
                    information_class=InformationClass.MEASURED),
        SafetyEvent(event_type=EventType.UTILITY_CONDITION, zone_id="zone-1",
                    value={"ventilation_flow_ratio": 0.55, "ventilation_status": "degraded"},
                    information_class=InformationClass.PREDICTED),
    ]
    for ev in events:
        g.apply_event(ev)
    return g


def test_flashfire_hyperedge_activates():
    g = build_flashfire_graph()
    engine = CompoundRuleEngine(g)
    activated = engine.evaluate()
    ids = {e.template_id for e in activated}
    assert "HE-042" in ids  # canonical id (HE-FLASHFIRE is a descriptive alias)
    he = next(e for e in activated if e.template_id == "HE-042")
    assert he.severity >= 0.8
    assert he.pathway == "toxic_exposure_or_flash_fire"


def test_no_activation_in_clean_state():
    g = SafetyHypergraph()
    g.bootstrap_steelforge()
    engine = CompoundRuleEngine(g)
    assert engine.evaluate() == []


def test_path_extraction_produces_factors_and_candidates():
    g = build_flashfire_graph()
    engine = CompoundRuleEngine(g)
    activated = engine.evaluate()
    extractor = PathExtractor(g)
    paths = extractor.extract_all(activated)
    assert paths
    p = paths[0]
    assert "gas_source" in p.contributing_factors
    assert "ignition_source" in p.contributing_factors
    # Should propose suspending the permit and evacuating the worker.
    types = {c.intervention_type for c in p.candidate_interventions}
    assert "suspend_permit" in types
    assert "evacuate_worker" in types


def test_minimum_cut_prefers_small_cheap_set():
    g = build_flashfire_graph()
    engine = CompoundRuleEngine(g)
    activated = engine.evaluate()
    paths = PathExtractor(g).extract_all(activated)
    rec = MinimumCausalCutOptimiser(safety_threshold=0.15).solve(paths)

    assert rec is not None
    assert rec.threshold_met, f"residual {rec.residual_risk} exceeds threshold"
    # The full-zone closure is HIGH cost; a good cut should avoid it if possible.
    closure_chosen = any(i.intervention_type == "close_zone" for i in rec.interventions)
    assert not closure_chosen or rec.total_cost_category != "HIGH" or len(rec.interventions) == 1
    # Every critical factor is covered.
    assert rec.covered_factors  # non-empty


def test_optimiser_breaks_every_sub_pathway():
    """The correct invariant: every live accident route is broken by >=1 action."""
    g = build_flashfire_graph()
    engine = CompoundRuleEngine(g)
    activated = engine.evaluate()
    paths = PathExtractor(g).extract_all(activated)
    rec = MinimumCausalCutOptimiser(0.15).solve(paths)

    for p in paths:
        for sp in p.sub_pathways:
            broken = any(
                bool(i.breaks_factors & sp.necessary_factors)
                for i in rec.interventions
            )
            assert broken, f"sub-pathway {sp.name} left unbroken"


def test_optimiser_avoids_zone_closure_when_cheaper_cut_exists():
    g = build_flashfire_graph()
    engine = CompoundRuleEngine(g)
    activated = engine.evaluate()
    paths = PathExtractor(g).extract_all(activated)
    rec = MinimumCausalCutOptimiser(0.15).solve(paths)
    types = {i.intervention_type for i in rec.interventions}
    assert "close_zone" not in types, "should not need the sledgehammer here"
    assert rec.total_cost_category in ("LOW", "MEDIUM")

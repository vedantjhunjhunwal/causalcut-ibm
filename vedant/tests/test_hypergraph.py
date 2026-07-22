"""Tests for SafetyHypergraph registration, edges and event listeners."""

from datetime import datetime, timezone

from app.engine.hypergraph_wrapper import SafetyHypergraph, Relation
from app.engine.types import EventType, InformationClass, NodeType, SafetyEvent


def make_graph() -> SafetyHypergraph:
    g = SafetyHypergraph()
    g.register_zone("zone-1", "Coke Oven", "gas_hazard", 200.0)
    g.register_worker("W-003", "zone-1")
    g.register_sensor("GS-03", "zone-1", "gas", "ppm")
    g.register_permit("PTW-007", "zone-1", "hot_work", "active", "W-003")
    g.register_barrier("FIRE-SUP-01", "zone-1", "fire_suppression")
    return g


def test_registration_creates_typed_nodes():
    g = make_graph()
    assert g.node("zone-1")["node_type"] == NodeType.ZONE.value
    assert "W-003" in g.nodes_of_type(NodeType.WORKER)
    assert "GS-03" in g.nodes_of_type(NodeType.SENSOR)
    assert g.node("W-003")["ppe_compliant"] is True


def test_base_edges_and_queries():
    g = make_graph()
    assert g.workers_in_zone("zone-1") == ["W-003"]
    assert g.active_permits_in_zone("zone-1") == ["PTW-007"]
    assert "GS-03" in g.sensors_in_zone("zone-1")


def test_add_edge_rejects_unknown_node():
    g = make_graph()
    try:
        g.add_base_edge("nope", "zone-1", Relation.IN_ZONE)
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_gas_event_updates_zone_state():
    g = make_graph()
    ev = SafetyEvent(
        event_type=EventType.GAS_ANOMALY,
        zone_id="zone-1",
        sensor_id="GS-03",
        value={"gas_type": "ammonia", "concentration_ppm": 215.0},
        information_class=InformationClass.MEASURED,
    )
    g.apply_event(ev)
    assert g.node("zone-1")["last_gas_ppm"] == 215.0
    assert g.node("GS-03")["value"] == 215.0


def test_ppe_event_marks_worker_noncompliant():
    g = make_graph()
    ev = SafetyEvent(
        event_type=EventType.PPE_VIOLATION,
        zone_id="zone-1",
        worker_id="W-003",
        value={"missing_ppe": ["hard_hat"]},
        information_class=InformationClass.MEASURED,
    )
    g.apply_event(ev)
    assert g.node("W-003")["ppe_compliant"] is False
    assert g.node("W-003")["ppe"]["hard_hat"] is False


def test_zone_adjacency_is_bidirectional():
    g = make_graph()
    g.register_zone("zone-4", "Utilities", "propagation")
    g.add_zone_adjacency("zone-1", "zone-4", "duct")
    assert "zone-4" in g.neighbors("zone-1", Relation.ADJACENT)
    assert "zone-1" in g.neighbors("zone-4", Relation.ADJACENT)


def test_snapshot_is_serializable():
    import json
    g = make_graph()
    snap = g.snapshot()
    json.dumps(snap)  # must not raise
    assert snap["factory_id"] == "steelforge-001"
    assert len(snap["nodes"]) == 5

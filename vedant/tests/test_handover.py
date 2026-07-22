"""Handover validation, audit log, and risk-engine tests (merged architecture).

The legacy in-process queue/consumer/replayer these once exercised were
replaced in the merge by the ingestion spine's EventQueue + ConsumerPool and
the RiskEngine. Pure-logic tests (handover rules, audit chain) are unchanged;
pipeline coverage now goes through RiskEngine.apply_canonical, the same path
the consumer pool uses in production.
"""

from datetime import datetime, timedelta, timezone

from app.analysis.handover_validator import HandoverValidator
from app.engine.hypergraph_wrapper import SafetyHypergraph
from app.engine.risk_engine import RiskEngine
from app.engine.types import ShiftHandover
from app.gateway.audit_log import AuditLog
from app.schemas.canonical import SafetyEventIn


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(**overrides):
    base = {
        "zone_id": "zone-1",
        "event_type": "gas_anomaly",
        "event_time": _iso(datetime.now(timezone.utc)),
        "value": {},
        "source": "test",
        "information_class": "M",
    }
    base.update(overrides)
    return SafetyEventIn(**base).to_canonical(None, timedelta(minutes=5))


# ------------------------------------------------------------------ #
# Handover validation (pure logic)
# ------------------------------------------------------------------ #
def _graph_with_active_permit() -> SafetyHypergraph:
    g = SafetyHypergraph()
    g.register_zone("zone-1", "Coke Oven", "gas_hazard")
    g.register_permit("PTW-007", "zone-1", "hot_work", "active")
    return g


def test_orphaned_permit_detected():
    v = HandoverValidator(_graph_with_active_permit())
    ho = ShiftHandover(
        zone_id="zone-1", outgoing_shift="A", incoming_shift="B",
        outgoing_officer="SO-A", incoming_officer="SO-B",
        acknowledged=False, open_permits=["PTW-007"],
    )
    assert "ORPHANED_PERMIT" in {i.kind for i in v.validate(ho)}


def test_missing_incoming_officer_detected():
    v = HandoverValidator(_graph_with_active_permit())
    ho = ShiftHandover(
        zone_id="zone-1", outgoing_shift="A", incoming_shift="B",
        outgoing_officer="SO-A", incoming_officer=None, acknowledged=True,
        open_permits=["PTW-007"],
    )
    assert "MISSING_INCOMING" in {i.kind for i in v.validate(ho)}


def test_clean_handover_has_no_issues():
    g = SafetyHypergraph()
    g.register_zone("zone-1", "Coke Oven")
    v = HandoverValidator(g)
    ho = ShiftHandover(
        zone_id="zone-1", outgoing_shift="A", incoming_shift="B",
        outgoing_officer="SO-A", incoming_officer="SO-B", acknowledged=True,
    )
    assert v.validate(ho) == []


# ------------------------------------------------------------------ #
# Risk engine (the merged pipeline path)
# ------------------------------------------------------------------ #
def test_risk_engine_produces_recommendation_from_canonical_events():
    engine = RiskEngine(safety_threshold=0.15)
    engine.graph.register_worker("W-003", "zone-1")

    events = [
        _canonical(event_type="permit_status", information_class="S", synthetic_flag=True,
                   value={"permit_id": "PTW-007", "permit_type": "hot_work", "status": "active"}),
        _canonical(event_type="gas_anomaly", value={"sensor_id": "GS-03", "concentration_ppm": 215.0}),
        _canonical(event_type="ppe_violation", worker_id="W-003",
                   value={"ppe": {"hard_hat": False}}),
        _canonical(event_type="utility_condition", information_class="P", model_version="vent-v1",
                   value={"ventilation_flow_ratio": 0.5}),
    ]
    for e in events:
        assert engine.apply_canonical(e) is True

    paths, rec = engine.evaluate()
    assert paths, "scenario should activate at least one accident path"
    assert rec is not None and rec.threshold_met
    types = {i.intervention_type for i in rec.interventions}
    assert "close_zone" not in types  # cheaper cut should win


def test_risk_engine_ignores_unhandled_event_types():
    engine = RiskEngine()
    # sensor_drift is a state-projection concern with no risk-graph handler;
    # the engine skips it cleanly rather than erroring.
    e = _canonical(event_type="sensor_drift", value={"sensor_id": "GS-03"})
    assert engine.apply_canonical(e) is False


def test_adapter_lifts_sensor_id_and_normalises_ppe():
    from app.engine.adapter import canonical_to_engine

    gas = canonical_to_engine(_canonical(
        event_type="gas_anomaly", value={"sensor_id": "GS-03", "concentration_ppm": 200}))
    assert gas.sensor_id == "GS-03"

    ppe = canonical_to_engine(_canonical(
        event_type="ppe_violation", worker_id="W-003",
        value={"ppe": {"hard_hat": False, "safety_vest": True}}))
    assert ppe.value["missing_ppe"] == ["hard_hat"]


# ------------------------------------------------------------------ #
# Audit log (write-ahead, hash-chained)
# ------------------------------------------------------------------ #
def test_audit_log_chain_and_verify(tmp_path):
    log = AuditLog(str(tmp_path / "audit"))
    for i in range(3):
        log.append(
            correlation_id=f"c{i}", recommendation_id="current",
            approver_id="SO-A", approver_role="shift_officer",
            decision="APPROVE", reason="test",
            interventions=[f"INT-{i}"], residual_risk=0.08,
        )
    ok, bad = log.verify_chain()
    assert ok and bad is None
    assert len(log.tail()) == 3


def test_audit_log_detects_tampering(tmp_path):
    import sqlite3
    log = AuditLog(str(tmp_path / "audit"))
    log.append(correlation_id="c0", recommendation_id="current", approver_id="SO-A",
               approver_role="shift_officer", decision="APPROVE", reason="ok",
               interventions=["INT-0"], residual_risk=0.08)
    log.append(correlation_id="c1", recommendation_id="current", approver_id="SO-A",
               approver_role="shift_officer", decision="APPROVE", reason="ok",
               interventions=["INT-1"], residual_risk=0.08)
    con = sqlite3.connect(log.db_path)
    con.execute("UPDATE audit SET decision='REJECT' WHERE seq=1")
    con.commit()
    con.close()
    ok, bad = log.verify_chain()
    assert not ok and bad == 1

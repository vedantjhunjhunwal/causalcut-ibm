"""Pipeline-ordering tests.

Proves the acceptance criteria that analysis happens strictly AFTER durable
persistence, queue processing and SQLite projection — not before.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app


def _feats(seed: int = 11, scale: float = 60.0) -> list[float]:
    return list(np.random.RandomState(seed).randn(128) * scale)


COKE = {
    "name": "Coke Oven Flash-Fire",
    "safety_threshold": 0.15,
    "zones": [
        {"zone_id": "zone-1", "name": "Coke Oven", "hazard_class": "gas_hazard",
         "ventilation_status": "degraded", "ventilation_flow_ratio": 0.55},
        {"zone_id": "zone-2", "name": "Blast Furnace", "hazard_class": "high_risk"},
    ],
    "zone_adjacency": [{"zone_a": "zone-1", "zone_b": "zone-2", "medium": "shared_duct"}],
    "sensors": [{"sensor_id": "GS-03", "zone_id": "zone-1"}],
    "workers": [{"worker_id": "W-003", "zone_id": "zone-1", "present": True,
                 "missing_ppe": ["hard_hat"]}],
    "permits": [{"permit_id": "PTW-007", "zone_id": "zone-1",
                 "permit_type": "hot_work", "status": "active"}],
    "gas_readings": [{"sensor_id": "GS-03", "zone_id": "zone-1",
                      "concentration_ppm": 0, "features": _feats(),
                      "offset_seconds": 450}],
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def coke_run(client):
    res = client.post("/api/v1/scenario/run", json=COKE)
    assert res.status_code == 200, res.text
    return res.json()


class TestPipelineOrdering:
    def test_analysis_runs_after_persistence(self, coke_run):
        p = coke_run["result"]["pipeline"]
        assert p["analysis_after_persistence"] is True
        assert p["completed"] is True
        assert p["timed_out"] is False

    def test_all_events_persisted_and_processed(self, coke_run):
        p = coke_run["result"]["pipeline"]
        assert p["ingestion"]["accepted"] > 0
        assert p["ingestion"]["rejected"] == 0, p["ingestion"]["details"]
        # Every accepted event traversed queue -> consumer -> projection.
        assert p["processed_events"] == p["expected_events"]
        assert p["failed_events"] == 0

    def test_queue_drained(self, coke_run):
        assert coke_run["result"]["pipeline"]["queue_depth_after"] == 0

    def test_stage_order_is_canonical(self, coke_run):
        order = coke_run["result"]["pipeline"]["order"]
        # persistence + queue must precede every analysis stage
        for analysis in ("rule_evaluation", "risk_propagation", "simulation",
                         "optimization", "regulatory_verification"):
            assert order.index("persisting_events") < order.index(analysis)
            assert order.index("queue_processing") < order.index(analysis)
            assert order.index("state_projection") < order.index(analysis)

    def test_events_reached_append_only_store(self, client, coke_run):
        cid = coke_run["result"]["pipeline"]["correlation_id"]
        rows = client.get("/api/v1/events?limit=200").json()["events"]
        assert any(r.get("correlation_id") == cid for r in rows), \
            "scenario events must be in the append-only event store"

    def test_events_projected_into_sqlite(self, client, coke_run):
        """The permit and worker from the scenario must be in plant state."""
        permits = client.get("/api/v1/state/permits").json()
        assert permits.get("count", 0) >= 1
        workers = client.get("/api/v1/state/workers").json()
        assert workers.get("count", 0) >= 1


class TestCanonicalRuleIdentity:
    def test_he_042_is_canonical(self, coke_run):
        ids = [r["id"] for r in coke_run["result"]["activated_rules"]]
        assert any(i.startswith("HE-042") for i in ids), ids

    def test_alias_resolves(self):
        from app.engine.compound_rules import canonical_rule_id
        assert canonical_rule_id("HE-FLASHFIRE") == "HE-042"
        assert canonical_rule_id("HE-FLASHFIRE:zone-1") == "HE-042:zone-1"
        assert canonical_rule_id("HE-042") == "HE-042"


class TestEventSemantics:
    def test_user_facts_are_observed_not_predicted(self):
        from app.schemas.scenario import Scenario
        s = Scenario.model_validate({
            "name": "semantics", "zones": [
                {"zone_id": "z1", "ventilation_status": "degraded",
                 "ventilation_flow_ratio": 0.5}],
            "assets": [{"asset_id": "A1", "zone_id": "z1", "failure_probability": 0.4}],
            "permits": [{"permit_id": "P1", "zone_id": "z1"}],
        })
        by_type = {str(e.event_type): e for e in s.to_events()}
        # user-entered ventilation + machine condition => observed (M)
        assert str(by_type["utility_condition"].information_class) == "M"
        assert str(by_type["equipment_failure"].information_class) == "M"
        # permits are synthetic records
        assert str(by_type["permit_status"].information_class) == "S"
        # and none of them claim a model
        for e in s.to_events():
            assert e.model_version is None

    def test_model_output_is_predicted_with_attribution(self):
        from app.engine.model_events import generate_model_events
        from app.schemas.scenario import Scenario
        s = Scenario.model_validate({
            "name": "m", "zones": [{"zone_id": "zone-1"}],
            "machine_readings": [{"asset_id": "M1", "zone_id": "zone-1", "Type": "L",
                                  "Air_temperature": 302.0, "Process_temperature": 310.2,
                                  "Rotational_speed": 1300, "Torque": 58.0,
                                  "Tool_wear": 200}],
        })
        events, prov = generate_model_events(s, "corr-sem")
        if not prov or not prov[0].get("ran"):
            pytest.skip("AI4I artifact unavailable")
        e = events[0]
        assert str(e.information_class) == "P"      # predicted
        assert e.model_version                       # real attribution
        assert e.value["inference_mode"] == "real"


class TestOperatorDecisionPersistence:
    def test_approve_then_duplicate_blocked(self, client):
        run_id = client.post("/api/v1/scenario/run", json=COKE).json()["run_id"]
        ok = client.post(f"/api/v1/scenario/{run_id}/decision",
                         json={"decision": "APPROVE", "reason": "ordering test"},
                         headers={"X-API-Key": "dev-key-so-a"})
        assert ok.status_code == 200
        assert isinstance(ok.json()["audit_seq"], int)
        dup = client.post(f"/api/v1/scenario/{run_id}/decision",
                          json={"decision": "APPROVE"},
                          headers={"X-API-Key": "dev-key-so-a"})
        assert dup.status_code == 409

    def test_reject_persisted(self, client):
        run_id = client.post("/api/v1/scenario/run", json=COKE).json()["run_id"]
        rej = client.post(f"/api/v1/scenario/{run_id}/decision",
                          json={"decision": "REJECT", "reason": "false positive"},
                          headers={"X-API-Key": "dev-key-so-a"})
        assert rej.status_code == 200
        assert rej.json()["decision"] == "REJECT"
        assert rej.json()["dispatched"] is False

    def test_audit_chain_valid(self, client):
        audit = client.get("/api/v1/risk/audit").json()
        assert audit["chain_valid"] is True
        assert len(audit["records"]) >= 1

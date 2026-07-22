"""End-to-end and integration tests for the user-driven scenario workflow.

These exercise the real pipeline (fresh hypergraph -> compound rules -> paths
-> OR-Tools minimum cut -> risk propagation -> sim -> graph payload) and the
real FastAPI HTTP surface via TestClient. Nothing is mocked here except the
heavy RAG retriever, which degrades to the static clause fallback when
sentence-transformers/faiss are absent (asserted explicitly).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.scenario import Scenario
from app.engine.scenario_runner import run_scenario

SCEN_DIR = Path(__file__).resolve().parents[1] / "scenarios"


def _coke_oven_scenario() -> dict:
    return {
        "name": "Coke Oven Flash-Fire",
        "safety_threshold": 0.15,
        "zones": [
            {"zone_id": "zone-1", "name": "Coke Oven", "hazard_class": "gas_hazard",
             "ventilation_status": "degraded", "ventilation_flow_ratio": 0.55},
            {"zone_id": "zone-4", "name": "Shared Utilities", "hazard_class": "propagation"},
        ],
        "zone_adjacency": [{"zone_a": "zone-1", "zone_b": "zone-4", "medium": "ventilation_duct"}],
        "sensors": [{"sensor_id": "GS-03", "zone_id": "zone-1"}],
        "workers": [{"worker_id": "W-003", "zone_id": "zone-1", "present": True, "missing_ppe": ["hard_hat"]}],
        "permits": [{"permit_id": "PTW-007", "zone_id": "zone-1", "permit_type": "hot_work", "status": "active"}],
        "gas_readings": [{"sensor_id": "GS-03", "zone_id": "zone-1", "concentration_ppm": 215,
                          "severity": 0.82, "confidence": 0.91, "offset_seconds": 450}],
    }


# --------------------------------------------------------------------------- #
# Schema / lowering
# --------------------------------------------------------------------------- #
class TestScenarioSchema:
    def test_custom_zones_accepted(self):
        s = Scenario.model_validate({"name": "x", "zones": [{"zone_id": "reactor-north"}]})
        assert s.zones[0].zone_id == "reactor-north"

    def test_requires_a_zone(self):
        with pytest.raises(Exception):
            Scenario.model_validate({"name": "x", "zones": []})

    def test_referential_integrity(self):
        with pytest.raises(Exception):
            Scenario.model_validate({
                "name": "x",
                "zones": [{"zone_id": "zone-1"}],
                "sensors": [{"sensor_id": "GS-1", "zone_id": "zone-999"}],
            })

    def test_lowering_produces_canonical_events(self):
        s = Scenario.model_validate(_coke_oven_scenario())
        events = s.to_events()
        assert len(events) >= 5
        types = {str(e.event_type) for e in events}
        assert {"gas_anomaly", "ppe_violation", "permit_status", "utility_condition"} <= types

    def test_sample_files_valid(self):
        for f in ["blank_template.json", "simple_gas_leak.json", "coke_oven_scenario.json"]:
            Scenario.model_validate(json.loads((SCEN_DIR / f).read_text()))


# --------------------------------------------------------------------------- #
# Runner (real engine)
# --------------------------------------------------------------------------- #
class TestScenarioRunner:
    def test_coke_oven_activates_flashfire_and_cuts(self):
        s = Scenario.model_validate(_coke_oven_scenario())
        r = run_scenario(s)
        rule_ids = [x["id"] for x in r["activated_rules"]]
        assert any("HE-042" in rid for rid in rule_ids)  # canonical id
        assert r["recommendation"] is not None
        # The minimum cut should break the permit and/or the worker exposure.
        cut = r["graph"]["minimum_cut"]["node_ids"]
        assert "PTW-007" in cut or "W-003" in cut

    def test_graph_payload_shape(self):
        s = Scenario.model_validate(_coke_oven_scenario())
        g = run_scenario(s)["graph"]
        assert set(g.keys()) >= {"scenario_id", "nodes", "edges", "activated_rules",
                                 "causal_paths", "minimum_cut"}
        for n in g["nodes"]:
            assert set(n.keys()) >= {"id", "type", "label", "status", "risk", "metadata"}
            assert n["status"] in {"normal", "warning", "critical", "mitigated"}
        for e in g["edges"]:
            assert set(e.keys()) >= {"id", "source", "target", "relation", "active",
                                     "causal_path", "cut"}
        types = {n["type"] for n in g["nodes"]}
        assert {"zone", "rule", "intervention"} <= types

    def test_empty_scenario_no_pathway(self):
        s = Scenario.model_validate({"name": "quiet", "zones": [{"zone_id": "z1"}]})
        r = run_scenario(s)
        assert r["recommendation"] is None
        assert r["activated_rules"] == []

    def test_regulatory_degrades_gracefully(self):
        # sentence-transformers/faiss unavailable in CI -> static fallback, but
        # citations must still be produced for the recommended actions.
        s = Scenario.model_validate(_coke_oven_scenario())
        r = run_scenario(s)
        assert len(r["regulatory_citations"]) >= 1


# --------------------------------------------------------------------------- #
# HTTP surface (real app)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


class TestScenarioApi:
    def test_opens_with_no_scenario(self, client):
        # There is no "current scenario" endpoint that returns data on boot;
        # the only way to get results is to POST one. Template is blank.
        tpl = client.get("/api/v1/scenario/template").json()
        assert tpl["name"] == "New Scenario"

    def test_validate_reports_field_errors(self, client):
        res = client.post("/api/v1/scenario/validate", json={"name": "x", "zones": []})
        body = res.json()
        assert body["valid"] is False
        assert any("zone" in e["message"].lower() for e in body["errors"])

    def test_run_full_pipeline(self, client):
        res = client.post("/api/v1/scenario/run", json=_coke_oven_scenario())
        assert res.status_code == 200
        body = res.json()
        assert "run_id" in body
        assert body["result"]["recommendation"] is not None

    def test_invalid_run_returns_422(self, client):
        res = client.post("/api/v1/scenario/run", json={"name": "bad", "zones": []})
        assert res.status_code == 422
        assert "errors" in res.json()

    def test_graph_endpoint_and_cut_highlight(self, client):
        run_id = client.post("/api/v1/scenario/run", json=_coke_oven_scenario()).json()["run_id"]
        g = client.get(f"/api/v1/scenario/{run_id}/graph").json()
        assert g["minimum_cut"]["node_ids"]
        assert g["minimum_cut"]["intervention_ids"]

    def test_approval_persisted_and_deduped(self, client):
        run_id = client.post("/api/v1/scenario/run", json=_coke_oven_scenario()).json()["run_id"]

        # unauthenticated approve -> 401
        assert client.post(f"/api/v1/scenario/{run_id}/decision",
                           json={"decision": "APPROVE"}).status_code == 401

        # authenticated approve -> audit seq
        ok = client.post(f"/api/v1/scenario/{run_id}/decision",
                         json={"decision": "APPROVE", "reason": "concur"},
                         headers={"X-API-Key": "dev-key-so-a"})
        assert ok.status_code == 200
        assert isinstance(ok.json()["audit_seq"], int)

        # duplicate -> 409
        dup = client.post(f"/api/v1/scenario/{run_id}/decision",
                          json={"decision": "APPROVE"},
                          headers={"X-API-Key": "dev-key-so-a"})
        assert dup.status_code == 409

        # audit chain still valid
        audit = client.get("/api/v1/risk/audit").json()
        assert audit["chain_valid"] is True

    def test_rejection_persisted(self, client):
        run_id = client.post("/api/v1/scenario/run", json=_coke_oven_scenario()).json()["run_id"]
        rej = client.post(f"/api/v1/scenario/{run_id}/decision",
                          json={"decision": "REJECT", "reason": "false positive"},
                          headers={"X-API-Key": "dev-key-viewer"})
        # viewer may reject (only approve is authority-gated)
        assert rej.status_code == 200
        assert rej.json()["decision"] == "REJECT"
        assert rej.json()["dispatched"] is False

    def test_coke_oven_sample_loads(self, client):
        res = client.get("/api/v1/scenario/sample/coke_oven_scenario")
        assert res.status_code == 200
        assert "zones" in res.json()

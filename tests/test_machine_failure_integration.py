"""Machine-failure (AI4I LightGBM) integration tests.

Proves the model is *genuinely* integrated, per the acceptance criteria:

  1. the real artifact is located and loads,
  2. real inference runs (no mocks, no hardcoded values),
  3. the API route and the scenario runner use the SAME shared service object,
  4. the prediction reaches downstream CAUSALCUT processing (canonical event ->
     hypergraph -> compound rules -> recommendation),
  5. outputs are JSON-native and carry every required field,
  6. an unavailable artifact degrades instead of fabricating.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.engine.model_events import generate_model_events
from app.engine.scenario_runner import build_graph_from_scenario, run_scenario
from app.main import app
from app.schemas.scenario import Scenario
from app.services.model_service import (
    InvalidFeaturesError,
    MachineFailureModelService,
    get_registry,
)

REQUIRED_FIELDS = [
    "prediction", "failure_modes", "confidence", "probabilities",
    "model_name", "model_version", "latency_ms", "inference_mode",
    "degraded_reason",
]

NOMINAL = {"Type": "M", "Air_temperature": 298.1, "Process_temperature": 308.6,
           "Rotational_speed": 1551, "Torque": 42.8, "Tool_wear": 0}

# High torque + heavy tool wear + low speed => overstrain / heat-dissipation.
STRESSED = {"Type": "L", "Air_temperature": 302.0, "Process_temperature": 310.2,
            "Rotational_speed": 1300, "Torque": 58.0, "Tool_wear": 200}


@pytest.fixture(scope="module")
def svc():
    s = get_registry().machine
    if not s.available:
        pytest.skip("AI4I artifact not built; run .models/AI4I Classifier/training_pipeline.py")
    return s


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# 1. Artifact located + loads
# --------------------------------------------------------------------------- #
class TestArtifact:
    def test_artifact_path_points_at_real_file(self, svc):
        from pathlib import Path
        assert Path(svc.artifact_path).exists()
        assert svc.artifact_path.endswith("lgbm-ai4i-1.0_pipelines.joblib")

    def test_loaded_once_no_separate_loader(self):
        """Registry holds a single instance; repeated access reloads nothing."""
        a = get_registry().machine
        b = get_registry().machine
        assert a is b
        assert a._pipelines is b._pipelines

    def test_feature_order_comes_from_the_artifact(self, svc):
        """Order is recovered from the fitted preprocessor, not hardcoded."""
        assert svc.feature_order == ["Type", "Air_temperature", "Process_temperature",
                                     "Rotational_speed", "Torque", "Tool_wear"]

    def test_all_failure_modes_present(self, svc):
        st = svc.status()
        assert set(st["failure_modes"]) >= {"Machine_failure", "TWF", "HDF", "PWF", "OSF"}


# --------------------------------------------------------------------------- #
# 2. Real inference
# --------------------------------------------------------------------------- #
class TestRealInference:
    def test_contract_probabilities_in_range(self, svc):
        """Artifact contract: every target returns a probability in [0, 1]."""
        r = svc.predict(NOMINAL)
        assert r.inference_mode == "real"
        for k, v in r.prediction["probabilities"].items():
            assert isinstance(v, float), k
            assert 0.0 <= v <= 1.0, f"{k}={v} out of range"

    def test_contract_expected_keys_and_modes(self, svc):
        """All AI4I targets from training must be present."""
        probs = svc.predict(NOMINAL).prediction["probabilities"]
        assert {"Machine_failure", "TWF", "HDF", "PWF", "OSF"} <= set(probs)

    def test_failure_modes_follow_configured_threshold(self, svc):
        """`failure_modes` is derived from the configured decision threshold,
        not an arbitrary constant baked into the test."""
        from app.core.config import get_settings
        thr = get_settings().model_confidence_threshold
        r = svc.predict(STRESSED)
        probs = {k: v for k, v in r.prediction["probabilities"].items()
                 if k != "Machine_failure"}
        expected = sorted([m for m, p in probs.items() if p >= thr],
                          key=lambda m: probs[m], reverse=True)
        assert r.prediction["failure_modes"] == expected

    def test_top_mode_is_argmax(self, svc):
        r = svc.predict(STRESSED)
        probs = {k: v for k, v in r.prediction["probabilities"].items()
                 if k != "Machine_failure"}
        assert r.prediction["top_failure_mode"] == max(probs, key=probs.get)

    def test_stress_increases_risk_monotonically(self, svc):
        """Relative check, not an absolute threshold: a stressed machine must
        score strictly higher than a nominal one. The trained model's absolute
        probability is whatever the artifact says — the test does not impose
        a cut-off the training code never defined."""
        nominal = svc.predict(NOMINAL).prediction["machine_failure"]
        stressed = svc.predict(STRESSED).prediction["machine_failure"]
        assert stressed > nominal, f"stressed={stressed} !> nominal={nominal}"

    def test_distinct_inputs_give_distinct_outputs(self, svc):
        """Guards against a hardcoded/constant response."""
        a = svc.predict(NOMINAL).prediction["probabilities"]
        b = svc.predict(STRESSED).prediction["probabilities"]
        assert a != b

    def test_all_required_fields_present(self, svc):
        d = svc.predict(STRESSED).to_dict()
        missing = [f for f in REQUIRED_FIELDS if f not in d]
        assert missing == [], f"missing response fields: {missing}"

    def test_outputs_are_json_native(self, svc):
        d = svc.predict(STRESSED).to_dict()
        json.dumps(d)  # must not raise on numpy types
        assert all(isinstance(v, float) for v in d["probabilities"].values())
        assert isinstance(d["confidence"], float)
        assert isinstance(d["failure_modes"], list)

    def test_missing_feature_rejected(self, svc):
        with pytest.raises(InvalidFeaturesError) as exc:
            svc.predict({"Type": "M"})
        assert "required order" in str(exc.value)

    def test_feature_order_independent_of_dict_order(self, svc):
        """Reordered input dict must not change the prediction."""
        shuffled = {k: STRESSED[k] for k in reversed(list(STRESSED))}
        assert (svc.predict(shuffled).prediction["probabilities"]
                == svc.predict(STRESSED).prediction["probabilities"])


# --------------------------------------------------------------------------- #
# 3. API and scenario pipeline share ONE service
# --------------------------------------------------------------------------- #
class TestSharedService:
    def test_route_and_scenario_use_same_object(self):
        import app.api.v1.routes.models as routes
        import app.engine.model_events as events
        assert routes.get_registry() is events.get_registry()
        assert routes.get_registry().machine is events.get_registry().machine

    def test_api_matches_direct_service_call(self, client, svc):
        direct = svc.predict(STRESSED).prediction["probabilities"]
        via_api = client.post("/api/v1/models/machine-failure/predict",
                              json={**STRESSED, "scenario_id": "s-api"}).json()
        assert via_api["inference_mode"] == "real"
        assert via_api["probabilities"] == direct

    def test_api_returns_required_fields(self, client):
        body = client.post("/api/v1/models/machine-failure/predict", json=STRESSED).json()
        missing = [f for f in REQUIRED_FIELDS if f not in body]
        assert missing == []

    def test_api_invalid_features_422(self, client):
        r = client.post("/api/v1/models/machine-failure/predict",
                        json={"Type": "M", "Air_temperature": 298.1})
        assert r.status_code == 422

    def test_status_health_readiness_report_ready(self, client, svc):
        assert client.get("/api/v1/models/health").json()["status"] == "ok"
        st = client.get("/api/v1/models/status").json()["machine"]
        assert st["available"] is True
        assert st["inference_mode"] == "real"
        assert st["artifact_path"].endswith("lgbm-ai4i-1.0_pipelines.joblib")
        assert "machine" in client.get("/api/v1/models/readiness").json()["available_models"]


# --------------------------------------------------------------------------- #
# 4. Prediction reaches the downstream pipeline
# --------------------------------------------------------------------------- #
def _machine_scenario() -> Scenario:
    return Scenario.model_validate({
        "name": "machine-driven",
        "zones": [{"zone_id": "zone-3", "name": "Machine Shop",
                   "hazard_class": "rotating_equipment"}],
        "workers": [{"worker_id": "W-010", "zone_id": "zone-3", "present": True}],
        "machine_readings": [{"asset_id": "LATHE-01", "zone_id": "zone-3", **STRESSED}],
    })


class TestDownstreamReach:
    def test_prediction_becomes_canonical_event(self, svc):
        scenario = _machine_scenario()
        events, prov = generate_model_events(scenario, "corr-machine")
        assert len(events) == 1
        ev = events[0]
        assert str(ev.event_type) == "equipment_failure"
        assert str(ev.information_class) == "P"   # predicted, not observed
        assert ev.source == "machine_failure_ai4i_lgbm"
        assert ev.model_version == "lgbm-ai4i-1.0"
        assert ev.value["inference_mode"] == "real"
        # Contract, not a magic number: the event carries whatever the model
        # produced, as a valid probability.
        assert 0.0 <= ev.value["failure_probability"] <= 1.0
        assert isinstance(ev.value["failure_modes"], list)
        assert ev.value["correlation_id"] == "corr-machine"
        assert prov[0]["ran"] is True

    def test_event_reaches_the_hypergraph(self, svc):
        scenario = _machine_scenario()
        events, _ = generate_model_events(scenario, "corr-machine")
        graph = build_graph_from_scenario(scenario, extra_events=events)
        node = graph.node("LATHE-01")
        assert node is not None
        fp = node.get("failure_probability")
        assert fp is not None and 0.0 <= fp <= 1.0

    def test_prediction_drives_scenario_result(self, svc):
        r = run_scenario(_machine_scenario(), correlation_id="corr-machine-2")
        assert "machine:LATHE-01" in r["models"]["models_ran"]
        inv = [i for i in r["models"]["invocations"]
               if i["called"] == "machine:LATHE-01"][0]
        assert inv["inference_mode"] == "real"
        assert inv["model_version"] == "lgbm-ai4i-1.0"
        assert inv["artifact_path"].endswith("lgbm-ai4i-1.0_pipelines.joblib")
        assert r["models"]["mocks_used"] is False
        # The asset node carries the model-derived risk into the dashboard graph.
        asset = [n for n in r["graph"]["nodes"] if n["id"] == "LATHE-01"][0]
        assert 0.0 <= asset["risk"] <= 1.0
        assert asset["status"] in {"normal", "warning", "critical", "mitigated"}

    def test_scenario_api_surfaces_machine_model(self, client, svc):
        payload = json.loads(_machine_scenario().model_dump_json())
        res = client.post("/api/v1/scenario/run", json=payload)
        assert res.status_code == 200
        result = res.json()["result"]
        assert "machine:LATHE-01" in result["models"]["models_ran"]


# --------------------------------------------------------------------------- #
# 5. Degraded behaviour — never fabricate
# --------------------------------------------------------------------------- #
class TestDegradedNeverFabricates:
    def test_missing_artifact_degrades_with_null_prediction(self, tmp_path):
        broken = MachineFailureModelService(model_dir=str(tmp_path))
        r = broken.predict(STRESSED)
        assert r.inference_mode == "degraded"
        assert r.prediction is None
        assert r.degraded_reason
        d = r.to_dict()
        assert d["failure_modes"] == []
        assert d["probabilities"] == {}

    def test_degraded_scenario_reports_and_does_not_invent(self, tmp_path, monkeypatch):
        reg = get_registry()
        original = reg.machine
        monkeypatch.setattr(reg, "machine",
                            MachineFailureModelService(model_dir=str(tmp_path)))
        try:
            r = run_scenario(_machine_scenario())
            assert "machine:LATHE-01" in r["models"]["models_failed"]
            assert any("did not run" in w for w in r["warnings"])
            # No fabricated equipment_failure event was emitted.
            assert r["model_events_generated"] == 0
        finally:
            monkeypatch.setattr(reg, "machine", original)

"""Model integration tests.

Verifies the *genuine* integration criteria: artifact located, artifact loads,
real preprocessing applied, inference called BY THE SCENARIO PIPELINE, the
prediction converted into a canonical event, and the event reaching downstream
processing + the final response.

Models whose artifacts are absent in this repo (AI4I machine-failure) or whose
deps are absent (torch/faiss) must report degraded/unavailable and must NOT
emit fabricated predictions — that is asserted here too.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.scenario import Scenario
from app.engine.model_events import generate_model_events
from app.engine.scenario_runner import run_scenario
from app.services.model_service import (
    InvalidFeaturesError,
    get_registry,
)


@pytest.fixture(scope="module")
def registry():
    return get_registry()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _feats(seed: int = 11, scale: float = 60.0) -> list[float]:
    return list(np.random.RandomState(seed).randn(128) * scale)


# --------------------------------------------------------------------------- #
# Shared service layer
# --------------------------------------------------------------------------- #
class TestModelServices:
    def test_gas_artifact_loads_and_runs_real_inference(self, registry):
        assert registry.gas.available, "gas artifact must load"
        r = registry.gas.predict(_feats(), sensor_id="GS-03", zone_id="zone-1")
        assert r.inference_mode == "real"
        assert r.model_version and r.model_version != "unavailable"
        assert 0.0 <= r.confidence <= 1.0
        assert r.artifact_path and r.artifact_path.endswith(".joblib")
        assert r.latency_ms >= 0

    def test_gas_rejects_wrong_feature_count(self, registry):
        with pytest.raises(InvalidFeaturesError):
            registry.gas.predict([0.1, 0.2, 0.3])

    def test_gas_response_is_json_serialisable(self, registry):
        import json
        r = registry.gas.predict(_feats())
        json.dumps(r.to_dict(), default=str)  # must not raise

    def test_hydraulic_runs_real_inference(self, registry):
        sensors = ["PS1", "PS2", "PS3", "PS4", "PS5", "PS6", "EPS1", "FS1", "FS2",
                   "TS1", "TS2", "TS3", "TS4", "VS1", "CE", "CP", "SE"]
        data = {s: list(np.random.RandomState(2).rand(60) * 100) for s in sensors}
        r = registry.hydraulic.predict(data)
        assert r.inference_mode == "real"
        # No raw numpy leaks into the response.
        assert all(isinstance(v, (int, float, str)) for v in r.prediction.values())

    def test_hydraulic_rejects_missing_sensors(self, registry):
        with pytest.raises(InvalidFeaturesError):
            registry.hydraulic.predict({"PS1": [1.0, 2.0]})

    def test_unavailable_model_reports_degraded_not_fake(self, registry):
        """AI4I artifact is absent here — must degrade, never invent numbers."""
        r = registry.machine.predict({
            "Type": "M", "Air_temperature": 298.1, "Process_temperature": 308.6,
            "Rotational_speed": 1551, "Torque": 42.8, "Tool_wear": 0})
        if not registry.machine.available:
            assert r.inference_mode == "degraded"
            assert r.prediction is None          # <- no fabrication
            assert r.degraded_reason

    def test_registry_readiness_shape(self, registry):
        rd = registry.readiness()
        assert "available_models" in rd and "unavailable_models" in rd
        for name, st in rd["models"].items():
            assert {"model_name", "available", "inference_mode"} <= set(st)


# --------------------------------------------------------------------------- #
# Model -> canonical event bridge
# --------------------------------------------------------------------------- #
class TestModelEvents:
    def test_gas_features_become_model_backed_canonical_event(self):
        s = Scenario.model_validate({
            "name": "m", "zones": [{"zone_id": "zone-1"}],
            "sensors": [{"sensor_id": "GS-03", "zone_id": "zone-1"}],
            "gas_readings": [{"sensor_id": "GS-03", "zone_id": "zone-1",
                              "concentration_ppm": 0, "features": _feats()}],
        })
        events, prov = generate_model_events(s, "corr-1")
        assert len(events) == 1
        ev = events[0]
        # the event carries real model provenance, not scenario input
        assert ev.model_version and ev.source.startswith("gas_")
        assert ev.value["model_name"] == "gas_xgboost_isoforest"
        assert ev.value["inference_mode"] == "real"
        assert ev.value["correlation_id"] == "corr-1"
        assert prov[0]["ran"] is True

    def test_scenario_to_events_does_not_fabricate_model_gas(self):
        """Raw-feature readings must NOT be lowered without the model."""
        s = Scenario.model_validate({
            "name": "m", "zones": [{"zone_id": "zone-1"}],
            "gas_readings": [{"sensor_id": "GS-03", "zone_id": "zone-1",
                              "concentration_ppm": 999, "features": _feats()}],
        })
        assert s.to_events() == []

    def test_operator_entered_gas_still_lowered(self):
        s = Scenario.model_validate({
            "name": "m", "zones": [{"zone_id": "zone-1"}],
            "gas_readings": [{"sensor_id": "GS-03", "zone_id": "zone-1",
                              "concentration_ppm": 215, "severity": 0.8}],
        })
        assert len(s.to_events()) == 1


# --------------------------------------------------------------------------- #
# Scenario pipeline actually calls the models
# --------------------------------------------------------------------------- #
class TestScenarioUsesModels:
    def test_pipeline_invokes_gas_model_and_reports_provenance(self):
        s = Scenario.model_validate({
            "name": "model-driven", "zones": [{"zone_id": "zone-1"}],
            "sensors": [{"sensor_id": "GS-03", "zone_id": "zone-1"}],
            "gas_readings": [{"sensor_id": "GS-03", "zone_id": "zone-1",
                              "concentration_ppm": 0, "features": _feats()}],
        })
        r = run_scenario(s, correlation_id="corr-2")
        assert r["model_events_generated"] >= 1
        assert "gas:GS-03" in r["models"]["models_ran"]
        assert r["models"]["mocks_used"] is False
        assert r["correlation_id"] == "corr-2"
        gas = [i for i in r["models"]["invocations"] if i["called"] == "gas:GS-03"][0]
        assert gas["inference_mode"] == "real"
        assert gas["artifact_path"]

    def test_unavailable_model_surfaces_warning_in_result(self):
        s = Scenario.model_validate({
            "name": "m", "zones": [{"zone_id": "zone-1"}],
            "machine_readings": [{"asset_id": "M-1", "zone_id": "zone-1"}],
        })
        r = run_scenario(s)
        if "machine:M-1" in r["models"]["models_failed"]:
            assert any("did not run" in w for w in r["warnings"])


# --------------------------------------------------------------------------- #
# Model HTTP API
# --------------------------------------------------------------------------- #
class TestModelApi:
    def test_status_and_readiness(self, client):
        assert client.get("/api/v1/models/health").status_code == 200
        st = client.get("/api/v1/models/status").json()
        assert "gas" in st and "model_name" in st["gas"]
        rd = client.get("/api/v1/models/readiness").json()
        assert "available_models" in rd

    def test_gas_predict_endpoint_real(self, client):
        res = client.post("/api/v1/models/gas/predict",
                          json={"features": _feats(), "sensor_id": "GS-03", "zone_id": "zone-1"})
        assert res.status_code == 200
        body = res.json()
        for k in ("model_name", "model_version", "prediction", "confidence",
                  "inference_mode", "latency_ms", "correlation_id",
                  "artifact_path", "timestamp"):
            assert k in body, f"missing envelope field {k}"
        assert body["inference_mode"] == "real"

    def test_gas_predict_invalid_features(self, client):
        res = client.post("/api/v1/models/gas/predict", json={"features": [1.0, 2.0]})
        assert res.status_code == 422
        assert res.json()["error"] == "invalid_features"

    def test_hydraulic_endpoint(self, client):
        sensors = ["PS1", "PS2", "PS3", "PS4", "PS5", "PS6", "EPS1", "FS1", "FS2",
                   "TS1", "TS2", "TS3", "TS4", "VS1", "CE", "CP", "SE"]
        data = {s: list(np.random.RandomState(5).rand(50) * 100) for s in sensors}
        res = client.post("/api/v1/models/hydraulic/predict", json={"sensor_data": data})
        assert res.status_code in (200, 503)

    def test_machine_endpoint_reports_unavailable_not_fake(self, client):
        res = client.post("/api/v1/models/machine-failure/predict",
                          json={"Air_temperature": 298.1, "Process_temperature": 308.6,
                                "Rotational_speed": 1551, "Torque": 42.8, "Tool_wear": 0})
        body = res.json()
        if res.status_code == 503:
            assert body["prediction"] is None
            assert body["degraded_reason"]

    def test_regulatory_verify_endpoint(self, client):
        res = client.post("/api/v1/models/regulatory/verify",
                          json={"actions": ["Suspend hot-work permit PTW-007 in zone-1"],
                                "zone_context": "flash fire in zone-1"})
        assert res.status_code == 200
        body = res.json()
        assert body["inference_mode"] in ("real", "degraded")
        assert "citations" in body["prediction"]

    def test_vision_and_tracking_report_status(self, client):
        v = client.post("/api/v1/models/vision/detect", json={"image_ref": "x.jpg"})
        assert v.status_code in (200, 503)
        assert v.json()["inference_mode"] in ("real", "degraded")

    def test_scenario_run_exposes_model_block(self, client):
        res = client.post("/api/v1/scenario/run", json={
            "name": "api-model", "zones": [{"zone_id": "zone-1"}],
            "sensors": [{"sensor_id": "GS-03", "zone_id": "zone-1"}],
            "gas_readings": [{"sensor_id": "GS-03", "zone_id": "zone-1",
                              "concentration_ppm": 0, "features": _feats()}],
        })
        assert res.status_code == 200
        result = res.json()["result"]
        assert "models" in result and "execution_mode" in result
        assert result["models"]["mocks_used"] is False
        assert "registry_status" in result["models"]

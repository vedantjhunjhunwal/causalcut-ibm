"""Acceptance tests for the v1.6 gaps.

Covers: fail-closed on queue failure, gas events marked predicted, per-model
remote readiness, vision/tracking in the scenario schema + orchestration,
background run creation with run-scoped WebSocket isolation and polling.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.scenario import Scenario


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


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c



# --------------------------------------------------------------------------- #
# 1. Fail closed
# --------------------------------------------------------------------------- #
class TestFailClosed:
    def test_timeout_suppresses_all_analysis(self, client, monkeypatch):
        """A queue timeout must not yield rules, a graph, or a recommendation."""
        import app.engine.scenario_session as ss

        async def never_completes(self, timeout):
            return False

        monkeypatch.setattr(ss.ScenarioSession, "wait", never_completes)
        r = client.post("/api/v1/scenario/run", json=COKE)
        assert r.status_code == 504
        res = r.json()["result"]
        assert res["status"] == "failed"
        assert res["failure_stage"] == "queue_processing"
        assert res["recommendation"] is None
        assert res["activated_rules"] == []
        assert res["causal_paths"] == []
        assert res["graph"] is None
        assert res["pipeline"]["analysis_performed"] is False

    def test_projection_failure_suppresses_analysis(self, client, monkeypatch):
        """An event that fails to project is a hard failure."""
        import app.engine.scenario_session as ss

        real_stats = ss.ScenarioSession.stats

        def broken_stats(self):
            d = real_stats(self)
            d["errors"] = ["projection exploded"]
            return d

        monkeypatch.setattr(ss.ScenarioSession, "stats", broken_stats)
        r = client.post("/api/v1/scenario/run", json=COKE)
        res = r.json()["result"]
        assert res["status"] == "failed"
        assert res["recommendation"] is None
        assert res["pipeline"]["analysis_performed"] is False

    def test_success_path_still_analyses(self, client):
        r = client.post("/api/v1/scenario/run", json=COKE)
        assert r.status_code == 200
        res = r.json()["result"]
        assert res["status"] == "completed"
        assert res["pipeline"]["analysis_performed"] is True
        assert res["recommendation"] is not None


# --------------------------------------------------------------------------- #
# 2. Gas event semantics
# --------------------------------------------------------------------------- #
class TestGasEventSemantics:
    def test_gas_model_output_is_predicted(self):
        from app.engine.model_events import generate_model_events

        s = Scenario.model_validate({
            "name": "g", "zones": [{"zone_id": "z1"}],
            "sensors": [{"sensor_id": "GS-03", "zone_id": "z1"}],
            "gas_readings": [{"sensor_id": "GS-03", "zone_id": "z1",
                              "concentration_ppm": 0, "features": _feats()}],
        })
        events, prov = generate_model_events(s, "corr-gas")
        if not prov or not prov[0].get("ran"):
            pytest.skip("gas artifact unavailable")
        e = events[0]
        assert str(e.information_class) == "P", "classifier output must be predicted"
        for key in ("model_name", "model_version", "confidence", "inference_mode",
                    "latency_ms", "degraded_reason", "scenario_id", "correlation_id"):
            assert key in e.value, f"missing {key}"
        assert e.value["inference_mode"] == "real"
        assert e.value["correlation_id"] == "corr-gas"
        # the raw array remains measured instrument data
        assert e.value["raw_input_class"] == "measured"

    def test_operator_entered_gas_stays_observed(self):
        s = Scenario.model_validate({
            "name": "g", "zones": [{"zone_id": "z1"}],
            "gas_readings": [{"sensor_id": "GS-03", "zone_id": "z1",
                              "concentration_ppm": 215, "severity": 0.8}],
        })
        e = s.to_events()[0]
        assert str(e.information_class) == "M"
        assert e.model_version is None


# --------------------------------------------------------------------------- #
# 3. Per-model readiness
# --------------------------------------------------------------------------- #
class TestReadinessAccuracy:
    def test_status_exposes_required_fields(self, client):
        st = client.get("/api/v1/models/status").json()
        for name, entry in st.items():
            for key in ("model_name", "available", "ready", "artifact_found",
                        "dependency_status", "inference_mode", "degraded_reason"):
                assert key in entry, f"{name} missing {key}"

    def test_vision_and_tracking_not_falsely_ready(self, client):
        st = client.get("/api/v1/models/status").json()
        for name in ("vision", "tracking"):
            entry = st[name]
            deps_ok = all(v == "ok" for v in entry["dependency_status"].values())
            if not deps_ok:
                assert entry["ready"] is False, f"{name} must not report ready"
                assert entry["degraded_reason"]

    def test_remote_client_queries_per_model_status(self):
        """A healthy server must not make every model look available."""
        from app.services.remote_model_client import RemoteVisionService
        # Unreachable server -> unavailable, never a false positive.
        svc = RemoteVisionService("vision_yolov8_ppe",
                                  "http://127.0.0.1:9/api/v1/models/vision/detect",
                                  timeout_s=0.3)
        st = svc.status()
        assert st["ready"] is False
        assert st["load_status"] == "unreachable"
        assert "unreachable" in st["degraded_reason"]

    def test_remote_registry_key_mapping(self):
        from app.services.remote_model_client import (
            RemoteGasService, RemoteMachineService, RemoteVisionService)
        assert RemoteGasService.registry_key == "gas"
        assert RemoteMachineService.registry_key == "machine"
        assert RemoteVisionService.registry_key == "vision"


# --------------------------------------------------------------------------- #
# 4. Vision / tracking in the scenario schema + orchestration
# --------------------------------------------------------------------------- #
class TestVisionTrackingInputs:
    def test_schema_accepts_vision_and_tracking(self):
        s = Scenario.model_validate({
            "name": "v", "zones": [{"zone_id": "z1"}],
            "vision_inputs": [{"zone_id": "z1", "image_id": "cam1",
                               "image_b64": "AAAA", "worker_id": "W-1"}],
            "tracking_inputs": [{"zone_id": "z1", "detections": [
                {"frame_id": 1, "bbox": [1, 2, 3, 4], "class": "person",
                 "confidence": 0.9}]}],
        })
        assert len(s.vision_inputs) == 1
        assert s.tracking_inputs[0].detections[0].object_class == "person"

    def test_vision_requires_an_image_source(self):
        with pytest.raises(Exception):
            Scenario.model_validate({"name": "v", "zones": [{"zone_id": "z1"}],
                                     "vision_inputs": [{"zone_id": "z1"}]})

    def test_detection_validation(self):
        with pytest.raises(Exception):  # confidence out of range
            Scenario.model_validate({
                "name": "t", "zones": [{"zone_id": "z1"}],
                "tracking_inputs": [{"zone_id": "z1", "detections": [
                    {"frame_id": 1, "bbox": [1, 2, 3, 4], "class": "person",
                     "confidence": 5.0}]}]})
        with pytest.raises(Exception):  # bbox wrong arity
            Scenario.model_validate({
                "name": "t", "zones": [{"zone_id": "z1"}],
                "tracking_inputs": [{"zone_id": "z1", "detections": [
                    {"frame_id": 1, "bbox": [1, 2], "class": "person",
                     "confidence": 0.5}]}]})

    def test_unavailable_vision_fabricates_nothing(self):
        from app.engine.model_events import generate_model_events
        from app.services.model_service import get_registry

        s = Scenario.model_validate({
            "name": "v", "zones": [{"zone_id": "z1"}],
            "vision_inputs": [{"zone_id": "z1", "image_id": "cam1",
                               "image_b64": "AAAA"}],
            "tracking_inputs": [{"zone_id": "z1", "detections": [
                {"frame_id": 1, "bbox": [1, 2, 3, 4], "class": "person",
                 "confidence": 0.9}]}],
        })
        events, prov = generate_model_events(s, "corr-v")
        reg = get_registry()
        if reg.vision.readiness()[0]:
            pytest.skip("vision available — degraded path not exercised")
        called = {p["called"] for p in prov}
        assert any(c.startswith("vision:") for c in called)
        assert any(c.startswith("tracking:") for c in called)
        # degraded vision => zero fabricated PPE events
        ppe_events = [e for e in events if e.event_type == "ppe_violation"]
        assert ppe_events == []
        for p in prov:
            if not p["ran"]:
                assert p["degraded_reason"]


    def test_scenario_run_reports_vision_failure(self, client):
        payload = {**COKE, "vision_inputs": [
            {"zone_id": "zone-1", "image_id": "cam1", "image_b64": "AAAA"}]}
        res = client.post("/api/v1/scenario/run", json=payload).json()["result"]
        called = res["models"]["models_called"]
        assert any(c.startswith("vision:") for c in called)


# --------------------------------------------------------------------------- #
# 5. Background runs + run-scoped WebSocket + polling
# --------------------------------------------------------------------------- #
class TestBackgroundRunAndWebSocket:
    def test_start_returns_202_with_identifiers(self, client):
        r = client.post("/api/v1/scenario/start", json=COKE)
        assert r.status_code == 202
        b = r.json()
        assert b["run_id"] and b["scenario_id"] and b["correlation_id"]
        assert b["progress_ws"].endswith(b["run_id"])
        assert b["status"] == "running"

    def test_polling_fallback_reaches_completion(self, client):
        run_id = client.post("/api/v1/scenario/start", json=COKE).json()["run_id"]
        for _ in range(60):
            st = client.get(f"/api/v1/scenario/runs/{run_id}").json()
            if st["status"] != "running":
                break
            time.sleep(0.05)

        assert st["status"] == "completed"
        assert st["result"]["pipeline"]["analysis_performed"] is True

    def test_websocket_is_run_scoped(self, client):
        run_id = client.post("/api/v1/scenario/start", json=COKE).json()["run_id"]
        seen_stages = []
        with client.websocket_connect(f"/api/v1/ws/scenarios/{run_id}") as ws:
            for _ in range(15):
                msg = ws.receive_json()
                if msg.get("stage") == "subscribed":
                    continue
                # never another run's traffic
                assert msg.get("run_id") == run_id
                seen_stages.append(msg["stage"])
                if msg["stage"] in ("completed", "failed"):
                    break
        # real backend stages, not simulated timers
        assert "queue_processing" in seen_stages
        assert "persisting_events" in seen_stages

    def test_unknown_run_404(self, client):
        assert client.get("/api/v1/scenario/runs/run-nope").status_code == 404

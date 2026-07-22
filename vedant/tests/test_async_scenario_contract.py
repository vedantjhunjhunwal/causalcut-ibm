"""Contract tests for the asynchronous scenario workflow the dashboard uses.

These pin the guarantees the frontend depends on:

* ``POST /scenario/start`` mints identifiers before any pipeline work happens.
* ``/ws/scenarios/{run_id}`` replays stages emitted before the client
  connected, so a browser that subscribes after the 202 response — or that
  reconnects after a dropped socket — still sees the whole run.
* A terminal WebSocket message implies the result is already fetchable from
  ``GET /scenario/runs/{run_id}`` (no read-your-write race).
* The polling fallback returns the backend's own recorded stages, not a
  synthetic approximation.
* ``vision_inputs`` / ``tracking_inputs`` are executed by the *main* scenario
  pipeline — the same run that persists events, drains the queue, projects
  SQLite state and builds the hypergraph — rather than as standalone tests.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

# A 1x1 PNG. Real bytes, so the vision service gets genuine input; whether it
# can decode it depends on whether the checkpoint/torch are installed, which is
# exactly the degradation path we want represented in provenance.
PNG_1PX_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)

BASE = {
    "name": "Async Contract Scenario",
    "safety_threshold": 0.15,
    "zones": [
        {"zone_id": "zone-1", "name": "Coke Oven", "hazard_class": "gas_hazard",
         "ventilation_status": "degraded", "ventilation_flow_ratio": 0.55},
    ],
    "workers": [{"worker_id": "W-003", "zone_id": "zone-1", "present": True}],
    "permits": [{"permit_id": "PTW-007", "zone_id": "zone-1",
                 "permit_type": "hot_work", "status": "active"}],
}

VISION_AND_TRACKING = {
    **BASE,
    "vision_inputs": [
        {"zone_id": "zone-1", "image_id": "cam1-frame-0",
         "image_b64": PNG_1PX_B64, "worker_id": "W-003", "offset_seconds": 0},
    ],
    "tracking_inputs": [
        {"zone_id": "zone-1", "offset_seconds": 0,
         "detections": [
             {"frame_id": 1, "bbox": [100, 120, 60, 140],
              "class": "person", "confidence": 0.91},
         ]},
    ],
}

TERMINAL = {"completed", "failed"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _wait(client, run_id, timeout=20.0):
    """Poll until the run settles; returns the final status body."""
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        body = client.get(f"/api/v1/scenario/runs/{run_id}").json()
        if body.get("status") != "running":
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not settle: {body}")


class TestStartContract:
    def test_start_is_non_blocking_and_mints_ids(self, client):
        r = client.post("/api/v1/scenario/start", json=BASE)
        assert r.status_code == 202
        b = r.json()
        # Everything the client needs to subscribe is present up front.
        assert b["run_id"] and b["scenario_id"] and b["correlation_id"]
        assert b["status"] == "running"
        assert b["progress_ws"] == f"/api/v1/ws/scenarios/{b['run_id']}"
        assert b["status_url"] == f"/api/v1/scenario/runs/{b['run_id']}"

    def test_invalid_scenario_still_rejected_synchronously(self, client):
        r = client.post("/api/v1/scenario/start", json={"name": "no zones"})
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_scenario"
        assert r.json()["errors"]


class TestProgressStream:
    def test_late_subscriber_replays_missed_stages(self, client):
        """The browser cannot connect before /start returns — it must not
        matter. Subscribe only after the run has fully finished."""
        run_id = client.post("/api/v1/scenario/start", json=BASE).json()["run_id"]
        _wait(client, run_id)

        stages = []
        with client.websocket_connect(f"/api/v1/ws/scenarios/{run_id}") as ws:
            for _ in range(40):
                msg = ws.receive_json()
                if msg.get("stage") == "subscribed":
                    continue
                assert msg["run_id"] == run_id
                stages.append(msg["stage"])
                if msg["stage"] in TERMINAL:
                    break

        # Real backend stages, recovered entirely from replay.
        assert "validating" in stages
        assert "persisting_events" in stages
        assert "queue_processing" in stages
        assert stages[-1] in TERMINAL

    def test_terminal_message_implies_result_is_fetchable(self, client):
        """The race the frontend would otherwise hit: react to 'completed',
        fetch the run, and find it still marked running with no result."""
        run_id = client.post("/api/v1/scenario/start", json=BASE).json()["run_id"]

        with client.websocket_connect(f"/api/v1/ws/scenarios/{run_id}") as ws:
            for _ in range(60):
                msg = ws.receive_json()
                if msg.get("stage") in TERMINAL:
                    break
            else:
                raise AssertionError("never observed a terminal stage")

        body = client.get(f"/api/v1/scenario/runs/{run_id}").json()
        assert body["status"] != "running"
        assert body["result"] is not None

    def test_messages_are_sequenced_for_dedup(self, client):
        run_id = client.post("/api/v1/scenario/start", json=BASE).json()["run_id"]
        _wait(client, run_id)
        seqs = []
        with client.websocket_connect(f"/api/v1/ws/scenarios/{run_id}") as ws:
            for _ in range(40):
                msg = ws.receive_json()
                if msg.get("stage") == "subscribed":
                    continue
                seqs.append(msg["seq"])
                if msg["stage"] in TERMINAL:
                    break
        assert seqs == sorted(seqs), "seq must be monotonic for client dedup"
        assert len(seqs) == len(set(seqs))


class TestPollingFallback:
    def test_poll_exposes_real_recorded_stages(self, client):
        run_id = client.post("/api/v1/scenario/start", json=BASE).json()["run_id"]
        body = _wait(client, run_id)

        assert body["stages"], "canonical stage vocabulary should be advertised"
        emitted = [m["stage"] for m in body["progress"]]
        # The same stages the socket carries — not a fabricated placeholder.
        assert "persisting_events" in emitted
        assert "queue_processing" in emitted
        assert emitted[-1] in TERMINAL
        for m in body["progress"]:
            assert m["run_id"] == run_id
            assert "label" in m


class TestVisionAndTrackingInMainPipeline:
    def test_inputs_are_executed_by_the_scenario_run(self, client):
        run_id = client.post("/api/v1/scenario/start",
                             json=VISION_AND_TRACKING).json()["run_id"]
        body = _wait(client, run_id)
        result = body["result"]

        called = result["models"]["models_called"]
        assert any(c.startswith("vision:") for c in called), called
        assert any(c.startswith("tracking:") for c in called), called

        # Provenance is recorded for each, whether it ran for real or degraded.
        by_name = {r["called"]: r for r in result["models"]["invocations"]}
        assert "vision:cam1-frame-0" in by_name
        assert "tracking:zone-1" in by_name
        for rec in (by_name["vision:cam1-frame-0"], by_name["tracking:zone-1"]):
            assert "inference_mode" in rec
            if not rec["ran"]:
                # Never fabricate a detection when the model is unavailable.
                assert rec["degraded_reason"]

    def test_run_still_completes_through_the_full_pipeline(self, client):
        """Attaching vision/tracking must not bypass or short-circuit the
        queue -> SQLite -> hypergraph path."""
        run_id = client.post("/api/v1/scenario/start",
                             json=VISION_AND_TRACKING).json()["run_id"]
        body = _wait(client, run_id)
        assert body["status"] == "completed"

        pipeline = body["result"]["pipeline"]
        assert pipeline["analysis_after_persistence"] is True
        assert pipeline["analysis_performed"] is True
        assert pipeline["completed"] is True
        assert pipeline["processed_events"] == pipeline["expected_events"]
        assert pipeline["failed_events"] == 0

    def test_unreadable_frame_degrades_instead_of_failing_the_run(self, client):
        """Operator-supplied images are untrusted input; a bad one must not
        take down the whole scenario."""
        payload = {**BASE, "vision_inputs": [
            {"zone_id": "zone-1", "image_id": "corrupt", "image_b64": "!!!not-base64!!!"}]}
        run_id = client.post("/api/v1/scenario/start", json=payload).json()["run_id"]
        body = _wait(client, run_id)

        assert body["status"] == "completed"
        rec = next(r for r in body["result"]["models"]["invocations"]
                   if r["called"] == "vision:corrupt")
        assert rec["ran"] is False
        assert rec["degraded_reason"]

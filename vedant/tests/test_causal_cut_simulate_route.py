from fastapi.testclient import TestClient

from app.main import app


def test_simulate_endpoint_returns_baseline_and_treated():
    with TestClient(app) as client:
        payload = {
            "zone_risk": {"zone-1": 0.55},
            "hazard_severity": {"zone-1": 0.8},
            "horizon_seconds": 60,
            "dt_seconds": 10,
            "close_barrier_edge": ["zone-1", "zone-4"],
            "close_barrier_at_s": 20,
            "close_barrier_magnitude": 0.05,
        }
        resp = client.post("/api/v1/causal-cut/simulate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert "zone-4" in body["baseline"]
        assert body["treated"] is not None
        assert max(body["treated"]["zone-4"]) < max(body["baseline"]["zone-4"])


def test_simulate_endpoint_baseline_only_without_intervention():
    with TestClient(app) as client:
        payload = {
            "zone_risk": {"zone-1": 0.55},
            "hazard_severity": {"zone-1": 0.8},
            "horizon_seconds": 30,
            "dt_seconds": 10,
        }
        resp = client.post("/api/v1/causal-cut/simulate", json=payload)
        assert resp.status_code == 200
        assert resp.json()["treated"] is None


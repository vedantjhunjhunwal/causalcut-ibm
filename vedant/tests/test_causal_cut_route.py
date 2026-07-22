from fastapi.testclient import TestClient

from app.main import app


def test_recommend_endpoint_returns_optimal_cut():
    client = TestClient(app)
    payload = {
        "zone_risk": {"zone-1": 0.55},
        "hazard_severity": {"zone-1": 0.8},
        "active_paths": ["HE-042"],
        "watch_zone": "zone-1",
        "candidates": [
            {"id": "suspend_permit", "action": "suspend_permit", "cost": 0.1, "latency_s": 10, "covers_paths": ["HE-042"]},
            {"id": "evacuate", "action": "evacuate_workers", "cost": 0.6, "latency_s": 120, "covers_paths": ["HE-042"]},
        ],
    }
    resp = client.post("/api/v1/causal-cut/recommend", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OPTIMAL"
    assert body["recommended_action_ids"] == ["suspend_permit"]


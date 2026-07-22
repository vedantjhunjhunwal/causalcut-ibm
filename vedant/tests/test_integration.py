"""End-to-end integration across the merged system.

Proves the two halves are actually wired together: events ingested through the
HTTP boundary (Tarun's spine) are both projected to the SQLite plant-state
store AND fed to the risk engine, which produces a minimum causal cut that can
then be approved through the authenticated, audited gateway.

    ingest -> persist -> project (SQLite)  ─┐
                                            ├─> same event stream
                     risk engine (graph) ──┘ -> cut -> approve -> audit
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


T0 = datetime.now(timezone.utc)

# The design-doc timeline spans ~450 plant-seconds. For ingestion we map it
# into the recent past ending at "now" so every event passes clock-sanity
# (not future) and none are stale (< 5 min old), while preserving strict order
# — which is what the risk graph's monotonic gas guard relies on.
_SPAN = 450.0
_WINDOW = 120.0  # compress into the last 2 minutes


def _at(sec: float) -> str:
    offset_from_now = (_SPAN - sec) * (_WINDOW / _SPAN)
    return _iso(T0 - timedelta(seconds=offset_from_now))


# The coke-oven escalation (design doc §8), as canonical ingest payloads.
SCENARIO = [
    {"zone_id": "zone-1", "event_type": "worker_presence", "worker_id": "W-003",
     "event_time": _at(0), "value": {"present": True}, "source": "cctv",
     "information_class": "M"},
    {"zone_id": "zone-1", "event_type": "permit_status",
     "event_time": _at(5), "information_class": "S", "synthetic_flag": True,
     "source": "permit_system",
     "value": {"permit_id": "PTW-007", "permit_type": "hot_work", "status": "active",
               "issued_to": "W-003"}},
    {"zone_id": "zone-1", "event_type": "gas_anomaly", "event_time": _at(180),
     "source": "gas_v2", "model_version": "xgb-gas-v2", "information_class": "M",
     "value": {"sensor_id": "GS-03", "gas_type": "ammonia", "concentration_ppm": 180.0}},
    {"zone_id": "zone-1", "event_type": "ppe_violation", "worker_id": "W-003",
     "event_time": _at(360), "source": "cctv", "information_class": "M",
     "value": {"camera_id": "CAM-01", "ppe": {"hard_hat": False, "safety_vest": True},
               "present": True}},
    {"zone_id": "zone-1", "event_type": "utility_condition", "event_time": _at(420),
     "source": "scada", "information_class": "P", "model_version": "vent-v1",
     "uncertainty": 0.1,
     "value": {"ventilation_flow_ratio": 0.55, "ventilation_status": "degraded"}},
    {"zone_id": "zone-1", "event_type": "gas_anomaly", "event_time": _at(450),
     "source": "gas_v2", "model_version": "xgb-gas-v2", "information_class": "M",
     "value": {"sensor_id": "GS-03", "gas_type": "ammonia", "concentration_ppm": 215.0}},
]


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CAUSALCUT_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CAUSALCUT_AUDIT_BASE_PATH", str(tmp_path / "audit"))
    monkeypatch.setenv("CAUSALCUT_LOG_JSON", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.app
    async with main_module.lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
class TestEndToEnd:
    async def _ingest_scenario(self, client: AsyncClient) -> None:
        r = await client.post("/api/v1/events/ingest/batch", json={"events": SCENARIO})
        assert r.status_code == 202
        assert r.json()["accepted"] == len(SCENARIO)
        # Let the consumer pool project + feed the risk engine.
        for _ in range(20):
            await asyncio.sleep(0.05)
            stats = (await client.get("/api/v1/stats")).json()
            if stats["queue"]["processed"] >= len(SCENARIO):
                break

    async def test_projection_and_risk_from_same_ingest(self, client):
        await self._ingest_scenario(client)

        # (a) State projected to SQLite plant-state store.
        zone = (await client.get("/api/v1/state/zones/zone-1")).json()
        assert any(s["sensor_id"] == "GS-03" and s["value"] == 215.0
                   for s in zone["sensor_readings"])
        permits = (await client.get("/api/v1/state/permits")).json()
        assert any(p["permit_id"] == "PTW-007" for p in permits["permits"])

        # (b) Risk engine produced the minimum causal cut from the same events.
        rec = (await client.get("/api/v1/risk/recommendation")).json()["recommendation"]
        assert rec is not None
        assert rec["threshold_met"] is True
        actions = {i["intervention_type"] for i in rec["interventions"]}
        assert "close_zone" not in actions  # cheaper cut preferred over sledgehammer

    async def test_approval_requires_authority_and_is_audited(self, client):
        await self._ingest_scenario(client)

        body = {"recommendation_id": "current", "decision": "APPROVE", "reason": "ack"}

        # No key -> 401
        r = await client.post("/api/v1/risk/approve", json=body)
        assert r.status_code == 401

        # Viewer -> 403 (insufficient authority to dispatch)
        r = await client.post("/api/v1/risk/approve", json=body,
                              headers={"X-API-Key": "dev-key-viewer"})
        assert r.status_code == 403

        # Shift officer -> 200, dispatched, audited
        r = await client.post("/api/v1/risk/approve", json=body,
                              headers={"X-API-Key": "dev-key-so-a"})
        assert r.status_code == 200
        assert r.json()["dispatched"] is True
        assert r.json()["approver"] == "SO-A"

        # Audit chain holds and contains the decision.
        audit = (await client.get("/api/v1/risk/audit")).json()
        assert audit["chain_valid"] is True
        assert audit["records"][-1]["decision"] == "APPROVE"

    async def test_handover_validation_endpoint(self, client):
        await self._ingest_scenario(client)
        ho = {
            "zone_id": "zone-1", "outgoing_shift": "A", "incoming_shift": "B",
            "outgoing_officer": "SO-A", "incoming_officer": "SO-B",
            "acknowledged": False, "open_permits": ["PTW-007"],
        }
        r = await client.post("/api/v1/handover/validate", json=ho)
        assert r.status_code == 200
        assert r.json()["consistent"] is False
        assert any(i["kind"] == "ORPHANED_PERMIT" for i in r.json()["inconsistencies"])

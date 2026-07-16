"""Day-1 acceptance tests.

These assert the things that are expensive to discover later: information-class
integrity, WAL, idempotency, and the persist-before-queue ordering.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.schemas.canonical import SafetyEvent, SafetyEventIn
from app.schemas.enums import EventType, InformationClass, ZoneId


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def gas_event(**overrides) -> dict:
    base = {
        "zone_id": "zone-1",
        "event_type": "gas_anomaly",
        "event_time": _iso(datetime.now(timezone.utc)),
        "validity_window": "PT5M",
        "value": {"sensor_id": "GS-03", "gas_type": "ammonia",
                  "concentration_ppm": 215.4},
        "severity": 0.82,
        "confidence": 0.91,
        "uncertainty": 0.15,
        "source": "gas_anomaly_module_v2",
        "model_version": "xgb-gas-v2.1.0",
        "provenance": "UCI_GasSensorDrift_Batch7",
        "information_class": "M",
        "synthetic_flag": False,
    }
    base.update(overrides)
    return base


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CAUSALCUT_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CAUSALCUT_LOG_JSON", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    import importlib

    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.app

    async with main_module.lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


# ------------------------------------------------------------------ #
# Schema invariants
# ------------------------------------------------------------------ #
class TestCanonicalSchema:
    def test_valid_event_round_trips(self):
        e = SafetyEventIn(**gas_event()).to_canonical("cid-1", timedelta(minutes=5))
        assert e.information_class is InformationClass.MEASURED
        assert e.validity_window == timedelta(minutes=5)
        assert e.expires_at == e.event_time + timedelta(minutes=5)
        # ISO-8601 duration survives serialisation, per design doc §5.1
        assert e.model_dump(mode="json")["validity_window"] == "PT5M"

    def test_measured_cannot_be_synthetic(self):
        with pytest.raises(ValidationError, match="cannot be synthetic"):
            SafetyEventIn(**gas_event(information_class="M", synthetic_flag=True)) \
                .to_canonical(None, timedelta(minutes=5))

    def test_synthetic_class_requires_flag(self):
        with pytest.raises(ValidationError, match="requires synthetic_flag"):
            SafetyEventIn(**gas_event(information_class="S", synthetic_flag=False)) \
                .to_canonical(None, timedelta(minutes=5))

    def test_prediction_must_name_its_model(self):
        with pytest.raises(ValidationError, match="requires model_version"):
            SafetyEventIn(**gas_event(information_class="P", model_version=None)) \
                .to_canonical(None, timedelta(minutes=5))

    def test_counterfactual_must_carry_uncertainty(self):
        with pytest.raises(ValidationError, match="non-zero uncertainty"):
            SafetyEventIn(**gas_event(information_class="C", uncertainty=0.0)) \
                .to_canonical(None, timedelta(minutes=5))

    def test_ppe_event_requires_worker(self):
        with pytest.raises(ValidationError, match="requires worker_id"):
            SafetyEventIn(**gas_event(event_type="ppe_violation")) \
                .to_canonical(None, timedelta(minutes=5))

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            SafetyEventIn(**gas_event(event_time="2026-07-11T10:30:00")) \
                .to_canonical(None, timedelta(minutes=5))

    def test_severity_bounded(self):
        with pytest.raises(ValidationError):
            SafetyEventIn(**gas_event(severity=1.4))

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            SafetyEventIn(**gas_event(rogue_field="injected"))

    def test_staleness(self):
        old = _iso(datetime.now(timezone.utc) - timedelta(minutes=10))
        e = SafetyEventIn(**gas_event(event_time=old)).to_canonical(
            None, timedelta(minutes=5)
        )
        assert e.is_stale()

    def test_payload_hash_is_content_addressed(self):
        a = SafetyEventIn(**gas_event()).to_canonical(None, timedelta(minutes=5))
        b = SafetyEventIn(**gas_event(event_time=_iso(a.event_time))).to_canonical(
            None, timedelta(minutes=5)
        )
        assert a.event_id != b.event_id       # different envelopes
        assert a.payload_hash() == b.payload_hash()  # same reading

    def test_event_is_immutable(self):
        e = SafetyEventIn(**gas_event()).to_canonical(None, timedelta(minutes=5))
        with pytest.raises(ValidationError):
            e.severity = 0.1


# ------------------------------------------------------------------ #
# API + storage
# ------------------------------------------------------------------ #
@pytest.mark.asyncio
class TestIngestion:
    async def test_health(self, client):
        r = await client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    async def test_wal_is_actually_on(self, client):
        r = await client.get("/api/v1/ready")
        assert r.status_code == 200
        assert r.json()["checks"]["database"]["journal_mode"].lower() == "wal"

    async def test_correlation_id_echoed(self, client):
        r = await client.get("/api/v1/health", headers={"X-Correlation-ID": "trace-42"})
        assert r.headers["X-Correlation-ID"] == "trace-42"

    async def test_ingest_accepts_and_persists(self, client):
        r = await client.post("/api/v1/events/ingest", json=gas_event())
        assert r.status_code == 202
        body = r.json()
        assert body["accepted"] == 1
        eid = body["results"][0]["event_id"]

        got = await client.get(f"/api/v1/events/{eid}")
        assert got.status_code == 200
        assert got.json()["information_class"] == "M"

    async def test_ingest_is_idempotent(self, client):
        eid = str(uuid.uuid4())
        payload = gas_event(event_id=eid)
        first = await client.post("/api/v1/events/ingest", json=payload)
        second = await client.post("/api/v1/events/ingest", json=payload)
        assert first.json()["accepted"] == 1
        assert second.json()["duplicates"] == 1
        assert second.json()["results"][0]["status"] == "duplicate"

    async def test_bad_event_rejected_with_envelope(self, client):
        r = await client.post(
            "/api/v1/events/ingest",
            json=gas_event(information_class="M", synthetic_flag=True),
        )
        assert r.status_code == 422
        assert r.json()["results"][0]["status"] == "rejected"

    async def test_future_event_rejected(self, client):
        future = _iso(datetime.now(timezone.utc) + timedelta(hours=1))
        r = await client.post("/api/v1/events/ingest", json=gas_event(event_time=future))
        assert r.json()["results"][0]["status"] == "rejected"
        assert "clock" in r.json()["results"][0]["detail"]

    async def test_batch_partial_success(self, client):
        good = gas_event()
        bad = gas_event(information_class="P", model_version=None)
        r = await client.post("/api/v1/events/ingest/batch",
                              json={"events": [good, bad, gas_event()]})
        assert r.status_code == 202
        body = r.json()
        assert body["accepted"] == 2 and body["rejected"] == 1

    async def test_projection_reaches_plant_state(self, client):
        await client.post("/api/v1/events/ingest", json=gas_event())
        await asyncio.sleep(0.3)  # let the consumer pool drain

        r = await client.get("/api/v1/state/zones/zone-1")
        assert r.status_code == 200
        sensors = r.json()["sensor_readings"]
        assert any(s["sensor_id"] == "GS-03" and s["value"] == 215.4 for s in sensors)
        # risk is [P]; it must not be fabricated on day 1
        assert r.json()["risk_score"] is None

    async def test_ppe_violation_projects_worker_state(self, client):
        payload = gas_event(
            event_type="ppe_violation",
            worker_id="W-003",
            value={"camera_id": "CAM-01", "ppe": {"hard_hat": False, "safety_vest": True},
                   "present": True},
            information_class="M",
        )
        await client.post("/api/v1/events/ingest", json=payload)
        await asyncio.sleep(0.3)

        r = await client.get("/api/v1/state/workers", params={"non_compliant_only": True})
        workers = r.json()["workers"]
        assert any(w["worker_id"] == "W-003" and w["ppe"]["hard_hat"] is False
                   for w in workers)

    async def test_permit_projects_to_registry(self, client):
        now = datetime.now(timezone.utc)
        payload = gas_event(
            event_type="permit_status",
            information_class="S",
            synthetic_flag=True,
            model_version=None,
            value={"permit_id": "PTW-007", "permit_type": "hot_work",
                   "status": "active", "issued_to": "W-001",
                   "valid_from": _iso(now - timedelta(hours=4)),
                   "valid_to": _iso(now + timedelta(hours=4))},
        )
        await client.post("/api/v1/events/ingest", json=payload)
        await asyncio.sleep(0.3)

        r = await client.get("/api/v1/state/permits")
        assert any(p["permit_id"] == "PTW-007" for p in r.json()["permits"])

    async def test_event_store_rejects_deletes(self, client):
        """Append-only is enforced by the database, not by good manners."""
        from app.db.session import get_db

        await client.post("/api/v1/events/ingest", json=gas_event())
        with pytest.raises(Exception, match="append-only"):
            await get_db().execute("DELETE FROM events")

    async def test_stats_by_information_class(self, client):
        await client.post("/api/v1/events/ingest", json=gas_event())
        await asyncio.sleep(0.2)
        r = await client.get("/api/v1/stats")
        assert r.json()["events_by_information_class"]["M"] >= 1
        assert r.json()["queue"]["processed"] >= 1

    async def test_openapi_generated(self, client):
        r = await client.get("/openapi.json")
        assert r.status_code == 200
        assert "/api/v1/events/ingest" in r.json()["paths"]

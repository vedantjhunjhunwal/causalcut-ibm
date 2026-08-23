"""Tests for the agent's read-only tool surface. No Gemini/LLM calls here —
these exercise app.engine.agent_tools directly against the real app state
(risk engine, db, audit log), the same way the existing HTTP routes do.

What's asserted:
  * The tool whitelist is exactly the declared tool set (no drift between
    TOOL_DECLARATIONS and ALLOWED_TOOL_NAMES).
  * Each read-only tool executes against real app state without raising.
  * The agent route is a real 503 (not a silent no-op) when disabled or
    unconfigured — the feature-flag contract this whole design depends on.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.engine.agent_tools import ALLOWED_TOOL_NAMES, TOOL_DECLARATIONS, AgentToolkit
from app.main import app


class _FakeRequest:
    """AgentToolkit only reads request.app.state.* — no need for a full
    Starlette Request in these tests."""

    def __init__(self, fastapi_app):
        self.app = fastapi_app


def test_tool_whitelist_matches_declarations():
    declared_names = {d["name"] for d in TOOL_DECLARATIONS}
    assert declared_names == ALLOWED_TOOL_NAMES


def test_no_write_or_auth_imports_in_agent_tools():
    """Structural guard: the tool module must never import the approval
    gateway. This is the hard boundary the whole design leans on."""
    import app.engine.agent_tools as mod

    src = open(mod.__file__).read()
    assert "app.gateway.auth" not in src
    assert "AuditLog(" not in src or "append(" not in src  # no write calls
    assert ".append(" not in src  # AuditLog.append is the only write method


@pytest.fixture()
def toolkit():
    with TestClient(app) as client:  # runs lifespan -> app.state populated
        yield AgentToolkit(_FakeRequest(client.app))


def test_get_active_paths_runs(toolkit):
    result = toolkit.get_active_paths()
    assert "active_paths" in result
    assert isinstance(result["count"], int)


def test_get_risk_recommendation_runs(toolkit):
    result = toolkit.get_risk_recommendation()
    assert "recommendation" in result


def test_get_model_health_runs(toolkit):
    result = toolkit.get_model_health()
    assert "status" in result and "readiness" in result


def test_get_audit_history_runs(toolkit):
    result = toolkit.get_audit_history(limit=5)
    assert "chain_valid" in result
    assert isinstance(result["records"], list)


def test_explain_rule_known_and_unknown(toolkit):
    known = toolkit.explain_rule("HE-042")
    assert known["rule_id"] == "HE-042"

    unknown = toolkit.explain_rule("NOT-A-RULE")
    assert unknown["error"] == "unknown_rule_id"


def test_get_osha_prior_known_and_unknown(toolkit):
    result = toolkit.get_osha_prior("toxic_gas_exposure")
    assert result["found"] is True
    assert "base_probability" in result

    missing = toolkit.get_osha_prior("not_a_real_hazard")
    assert missing["found"] is False
    assert isinstance(missing["available_hazard_types"], list)


def test_verify_action_compliance_returns_a_verdict(toolkit):
    result = toolkit.verify_action_compliance("Suspend hot work permit PTW-007", "gas rising")
    assert "compliance_status" in result


def test_explain_current_cut_handles_no_recommendation(toolkit):
    result = toolkit.explain_current_cut()
    assert "has_recommendation" in result


@pytest.mark.asyncio
async def test_get_zone_status_runs(toolkit):
    result = await toolkit.get_zone_status("zone-1")
    assert result["zone_id"] == "zone-1"
    assert "sensor_readings" in result


@pytest.mark.asyncio
async def test_check_sensor_drift_handles_no_history(toolkit):
    result = await toolkit.check_sensor_drift("SENSOR-DOES-NOT-EXIST")
    assert "drift_detected" in result


def test_agent_route_503_when_disabled():
    with TestClient(app) as client:
        resp = client.post("/api/v1/agent/chat", json={"message": "status of zone-1?"})
        assert resp.status_code == 503
        assert resp.json()["error"] in {"agent_disabled", "agent_unavailable"}


def test_agent_status_reports_disabled_by_default():
    with TestClient(app) as client:
        resp = client.get("/api/v1/agent/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["read_only"] is True
        assert body["enabled"] is False

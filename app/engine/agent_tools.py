"""Read-only tool surface for the CausalCut Safety Intelligence agent.

Every function on ``AgentToolkit`` is a thin adapter over modules the REST
API already exposes -- ``RiskEngine``, the repositories, the model registry,
the audit log, the regulatory RAG verifier. No tool invents a new query or
duplicates business logic; each one calls the exact same method its
equivalent HTTP route calls.

Hard boundary (read this before adding a tool)
-----------------------------------------------
This class holds NO reference to ``AuthService`` or ``AuditLog.append`` and
imports nothing from ``app.gateway``. That is deliberate: an agent tool must
never be able to approve, dispatch, or write plant state. If a future tool
needs to *propose* something (e.g. a draft incident report), it must land in
a table tagged ``status="agent_proposed"`` and go through the same human
approval surface as every other recommendation -- never a direct write.

Every method here is JSON-serialisable-dict in, JSON-serialisable-dict out,
so results can be handed straight to the LLM as a function-call response.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import Request

from app.db.repositories import (
    EventRepository,
    PermitRepository,
    ScenarioRepository,
    SensorTelemetryRepository,
    WorkerZoneRepository,
)
from app.engine.drift_monitor import SensorDriftMonitor
from app.engine.risk_engine import RiskEngine
from app.gateway.audit_log import AuditLog

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OSHA_PRIORS_PATH = _REPO_ROOT / "risk_priors" / "osha_risk_priors.json"

_osha_cache: dict[str, Any] | None = None
_drift_monitor = SensorDriftMonitor()
_compliance_verifier: Any = None


def _get_compliance_verifier() -> Any | None:
    """Lazily import + cache regulatory_rag.verifier.ComplianceVerifier.

    Returns None (never raises) if faiss/sentence-transformers or the
    corpus itself are unavailable -- callers must treat that as "degraded",
    same as every other optional-dependency subsystem in this project.
    """
    global _compliance_verifier
    if _compliance_verifier is None:
        try:
            import sys
            rag_dir = str(_REPO_ROOT / "regulatory_rag")
            if rag_dir not in sys.path:
                sys.path.insert(0, rag_dir)
            from regulatory_rag.verifier import ComplianceVerifier

            _compliance_verifier = ComplianceVerifier()
        except Exception:
            _compliance_verifier = False  # sentinel: tried and failed
    return _compliance_verifier or None


def _load_osha_priors() -> dict[str, Any]:
    global _osha_cache
    if _osha_cache is None:
        try:
            _osha_cache = json.loads(_OSHA_PRIORS_PATH.read_text())
        except Exception as exc:  # pragma: no cover - missing/corrupt file
            _osha_cache = {"hazard_base_rates": {}, "_error": str(exc)}
    return _osha_cache


class AgentToolkit:
    """Bound, read-only view over one request's app state."""

    def __init__(self, request: Request) -> None:
        self._risk_engine: RiskEngine = request.app.state.risk_engine
        self._audit: AuditLog = request.app.state.audit
        db = request.app.state.db
        self._permits = PermitRepository(db)
        self._workers = WorkerZoneRepository(db)
        self._telemetry = SensorTelemetryRepository(db)
        self._scenarios = ScenarioRepository(db)
        self._events = EventRepository(db)

    # ------------------------------------------------------------ state --
    def list_zones(self) -> dict[str, Any]:
        """List all zone IDs currently tracked in the safety hypergraph."""
        zone_ids = self._risk_engine.graph.nodes_of_type_zone()
        return {"zones": sorted(zone_ids), "count": len(zone_ids)}

    async def get_zone_status(self, zone_id: str) -> dict[str, Any]:
        """Sensors, worker presence and active permits for one zone."""
        sensors = await self._telemetry.latest_for_zone(zone_id)
        present = await self._workers.in_zone(zone_id)
        active_permits = await self._permits.active_in_zone(zone_id)
        return {
            "zone_id": zone_id,
            "sensor_readings": [
                {
                    "sensor_id": s["sensor_id"],
                    "kind": s["sensor_kind"],
                    "value": s["value_num"],
                    "unit": s["unit"],
                    "stale": bool(s["stale"]),
                    "drift_flagged": bool(s["drift_flag"]),
                }
                for s in sensors
            ],
            "workers_present": [
                {
                    "worker_id": w["worker_id"],
                    "ppe_compliant": bool(w["ppe_compliant"]),
                    "last_seen_at": w["last_seen_at"],
                }
                for w in present
            ],
            "active_permits": [
                {"permit_id": p["permit_id"], "type": p["permit_type"], "valid_to": p["valid_to"]}
                for p in active_permits
            ],
        }

    async def list_non_compliant_workers(self) -> dict[str, Any]:
        """PPE violations across the whole plant, not scoped to one zone."""
        rows = await self._workers.non_compliant()
        return {
            "count": len(rows),
            "workers": [
                {"worker_id": r["worker_id"], "zone_id": r["zone_id"], "last_seen_at": r["last_seen_at"]}
                for r in rows
            ],
        }

    async def check_sensor_drift(self, sensor_id: str, lookback: int = 200) -> dict[str, Any]:
        """ADWIN concept-drift check over a sensor's recent scalar history.

        See app/engine/drift_monitor.py for why this runs at the scalar
        (per-sensor) granularity rather than the raw 128-dim feature vector.
        """
        rows = await self._telemetry.history(sensor_id, limit=lookback)
        values = [r["value_num"] for r in reversed(rows) if r["value_num"] is not None]
        return _drift_monitor.check(sensor_id, values)

    # ------------------------------------------------------- risk engine --
    def get_risk_recommendation(self) -> dict[str, Any]:
        """The current minimum-causal-cut, if any active path needs one."""
        return self._risk_engine.recommendation_payload()

    def get_active_paths(self) -> dict[str, Any]:
        """Active accident pathways currently tracked in the hypergraph."""
        return self._risk_engine.paths_payload()

    def explain_rule(self, rule_id: str) -> dict[str, Any]:
        """Plain-language identity of a compound rule (e.g. 'HE-042')."""
        for rule in self._risk_engine.rules.rules:
            if rule.template_id == rule_id:
                return {
                    "rule_id": rule.template_id,
                    "name": rule.name,
                    "pathway": rule.pathway,
                    "applies_to_hazard_classes": list(rule.applies_to_hazard_classes) or ["all zones"],
                }
        return {"error": "unknown_rule_id", "rule_id": rule_id}

    def explain_current_cut(self) -> dict[str, Any]:
        """Narrated explanation of the current cut: interventions, residual
        risk, and the regulatory basis for each intervention, via the same
        ExplanationRenderer and ComplianceVerifier the rest of the system
        uses -- not a new template invented for the agent."""
        _, rec = self._risk_engine.current()
        if rec is None:
            return {"has_recommendation": False, "message": "No active minimum-causal-cut right now."}

        rec_dict = rec.to_dict()
        interventions = rec_dict["interventions"]

        verifier = _get_compliance_verifier()
        if verifier is not None:
            try:
                actions_joined = "; ".join(i["action"] for i in interventions)
                verify_result = verifier.verify_action(actions_joined)
            except Exception as exc:  # pragma: no cover - defensive
                verify_result = {"compliance_status": "unverified", "evidence": [], "error": str(exc)}
        else:
            verify_result = {
                "compliance_status": "unverified",
                "evidence": [],
                "reason": "regulatory RAG unavailable (faiss/sentence-transformers not installed)",
            }

        try:
            import sys
            root_str = str(_REPO_ROOT)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)
            from explanations.renderer import ExplanationRenderer

            renderer = ExplanationRenderer()
            narrative = renderer.render_explanation(
                {
                    "interventions": [{"action": i["action"]} for i in interventions],
                    "risk_before": None,
                    "residual_risk": rec_dict["residual_risk"],
                    "total_cost": rec_dict["total_cost"],
                },
                {
                    "compliance_status": verify_result.get("compliance_status", "unverified"),
                    "evidence": verify_result.get("evidence", []),
                },
            )
        except Exception as exc:  # pragma: no cover - renderer import issue
            narrative = None
            narrative_error = str(exc)
        else:
            narrative_error = None

        return {
            "has_recommendation": True,
            "recommendation": rec_dict,
            "compliance": verify_result,
            "narrative": narrative,
            "narrative_error": narrative_error,
            "requires_human_approval": True,
        }

    def verify_action_compliance(self, action: str, zone_context: str = "") -> dict[str, Any]:
        """Check a PROPOSED action against the real regulatory corpus, using
        the same ComplianceVerifier the design doc's §4.9 "is the proposed
        cut legal?" check calls for.

        Read-only: this only retrieves and assesses; it never approves or
        dispatches anything. The result is advisory input for a human.
        """
        verifier = _get_compliance_verifier()
        if verifier is None:
            return {
                "verified": False,
                "compliance_status": "unverified",
                "reason": "regulatory RAG unavailable (faiss/sentence-transformers not installed)",
                "evidence": [],
            }
        return verifier.verify_action(action, zone_context)

    def simulate_what_if(
        self,
        watch_zone: str,
        close_barrier_edge: tuple[str, str] | None = None,
        horizon_seconds: float = 300.0,
        dt_seconds: float = 10.0,
    ) -> dict[str, Any]:
        """Counterfactual risk trajectory for a zone, baseline vs. one
        candidate intervention, using the SAME SimPy propagation model as
        POST /causal-cut/simulate -- seeded from the live hypergraph."""
        from app.engine.risk_propagator import PropagationInputs
        from app.simulation.counterfactual_sim import CounterfactualSimulator, Intervention

        graph = self._risk_engine.graph
        zone_risk: dict[str, float] = {}
        hazard_severity: dict[str, float] = {}
        for zone_id in graph.nodes_of_type_zone():
            node = graph.node(zone_id)
            ppm = node.get("last_gas_ppm") or 0.0
            severity = max(0.0, min(1.0, ppm / 300.0))
            zone_risk[zone_id] = severity
            hazard_severity[zone_id] = severity

        prop_inputs = PropagationInputs(risk=zone_risk, hazard_severity=hazard_severity, barrier_multiplier={})
        sim = CounterfactualSimulator(prop_inputs, dt_seconds=dt_seconds, horizon_seconds=horizon_seconds)
        baseline = sim.run_baseline()

        result: dict[str, Any] = {
            "watch_zone": watch_zone,
            "baseline_final_risk": round(baseline.final_risk(watch_zone), 4),
            "baseline_peak_risk": round(baseline.peak_risk(watch_zone), 4),
            "info_class": "C",  # counterfactual estimate
        }

        if close_barrier_edge is not None:
            treated = sim.run_with_interventions([
                Intervention(time_s=0.0, action="close_barrier", target=close_barrier_edge, magnitude=0.05)
            ])
            result["treated_final_risk"] = round(treated.final_risk(watch_zone), 4)
            result["treated_peak_risk"] = round(treated.peak_risk(watch_zone), 4)
            result["risk_reduction"] = round(
                CounterfactualSimulator.risk_reduction(baseline, treated, watch_zone), 4
            )
        else:
            result["note"] = "No intervention supplied — baseline trajectory only."

        return result

    # -------------------------------------------------------- model layer --
    def get_model_health(self) -> dict[str, Any]:
        """Which model subsystems are real vs degraded right now, so the
        agent can honestly caveat what it's telling the operator."""
        from app.services.model_service import get_registry

        registry = get_registry()
        return {"status": registry.status_all(), "readiness": registry.readiness()}

    # ------------------------------------------------------------- audit --
    def get_audit_history(self, limit: int = 10) -> dict[str, Any]:
        """Tail of the hash-chained operator-decision log (read-only)."""
        ok, first_bad = self._audit.verify_chain()
        return {"chain_valid": ok, "first_bad_seq": first_bad, "records": self._audit.tail(limit)}

    # ------------------------------------------------ scenario history --
    async def get_scenario_history(self, factory_id: str | None = None, limit: int = 20) -> dict[str, Any]:
        """List past scenario definitions stored in the database.

        Survives server restarts — reads from Supabase, not in-memory.
        """
        scenarios = await self._scenarios.list_scenarios(factory_id=factory_id, limit=limit)
        return {"scenarios": scenarios, "count": len(scenarios)}

    async def get_scenario_runs(self, factory_id: str | None = None,
                                scenario_id: str | None = None,
                                limit: int = 20) -> dict[str, Any]:
        """List past scenario run results from the database.

        Each entry includes run_id, status, execution_mode, residual_risk,
        processed_events, failure_reason, and timestamps.  Survives restarts.
        """
        runs = await self._scenarios.list_runs(
            factory_id=factory_id, scenario_id=scenario_id, limit=limit,
        )
        return {"runs": runs, "count": len(runs)}

    async def get_scenario_run_detail(self, run_id: str) -> dict[str, Any]:
        """Fetch the full result of a specific scenario run from the database.

        Includes recommendation, causal_paths, activated_rules, pipeline
        metadata, and models_ran.  Survives server restarts.
        """
        row = await self._scenarios.get_run(run_id)
        if row is None:
            return {"error": "not_found", "run_id": run_id}
        return {"run": row}

    async def get_recent_events(self, limit: int = 20,
                                zone_id: str | None = None,
                                event_type: str | None = None) -> dict[str, Any]:
        """List recent safety events from the persistent event store.

        Each event has event_type, zone_id, severity, value, information_class,
        and timestamp.  Survives server restarts.
        """
        events = await self._events.list_recent(
            limit=limit, zone_id=zone_id, event_type=event_type,
        )
        return {"events": events, "count": len(events)}

    # ------------------------------------------------------ risk priors --
    def get_osha_prior(self, hazard_type: str) -> dict[str, Any]:
        """Historical OSHA base rate + severity weight for a hazard type,
        parsed from the official severe-injury dataset (see
        risk_priors/osha_parser.py) -- for grounding a model's probability
        in a real-world historical frequency, not just presenting it bare."""
        priors = _load_osha_priors()
        rates = priors.get("hazard_base_rates", {})
        if hazard_type in rates:
            return {"hazard_type": hazard_type, "found": True, **rates[hazard_type]}
        return {
            "hazard_type": hazard_type,
            "found": False,
            "available_hazard_types": sorted(rates.keys()),
        }


# ---------------------------------------------------------------------------
# Tool schema (Gemini function-calling declarations) + name -> method map.
# Kept in this module, next to the implementations, so the two can never
# drift apart silently.
# ---------------------------------------------------------------------------

TOOL_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "list_zones",
        "description": "List all zone IDs currently tracked in the safety hypergraph. Call this first when the operator asks about 'all zones' or doesn't specify a zone.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_zone_status",
        "description": "Get live sensor readings, worker presence and active permits for one plant zone.",
        "parameters": {
            "type": "object",
            "properties": {"zone_id": {"type": "string", "description": "e.g. 'zone-1'"}},
            "required": ["zone_id"],
        },
    },
    {
        "name": "list_non_compliant_workers",
        "description": "List all workers currently flagged as PPE non-compliant, plant-wide.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "check_sensor_drift",
        "description": "Check whether a sensor's recent readings show statistically significant drift (ADWIN).",
        "parameters": {
            "type": "object",
            "properties": {
                "sensor_id": {"type": "string"},
                "lookback": {"type": "integer", "description": "How many recent readings to check (default 200)"},
            },
            "required": ["sensor_id"],
        },
    },
    {
        "name": "get_risk_recommendation",
        "description": "Get the current minimum-causal-cut recommendation, if the plant has any active risk path.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_active_paths",
        "description": "List currently active accident pathways in the safety hypergraph.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "explain_rule",
        "description": "Explain what a compound safety rule (e.g. 'HE-042') means in plain language.",
        "parameters": {
            "type": "object",
            "properties": {"rule_id": {"type": "string"}},
            "required": ["rule_id"],
        },
    },
    {
        "name": "explain_current_cut",
        "description": (
            "Give a full narrated explanation of the current recommended minimum-causal-cut: "
            "which interventions, why, residual risk, and the regulatory citations behind it."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "verify_action_compliance",
        "description": "Check whether a proposed (not-yet-approved) action conflicts with the regulatory corpus.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "e.g. 'Suspend hot work permit PTW-007'"},
                "zone_context": {"type": "string", "description": "Optional extra context, e.g. current gas ppm"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "simulate_what_if",
        "description": (
            "Run a counterfactual 'what happens if we do/don't act' risk trajectory for a zone, "
            "optionally closing a named barrier edge as the intervention."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "watch_zone": {"type": "string"},
                "horizon_seconds": {"type": "number", "description": "How far ahead to simulate (default 300s)"},
            },
            "required": ["watch_zone"],
        },
    },
    {
        "name": "get_model_health",
        "description": "Report which ML/RAG subsystems (gas, hydraulic, machine-failure, vision, RAG) are real vs degraded right now.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_audit_history",
        "description": "Read the tail of the tamper-evident operator-decision audit log.",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "How many records (default 10)"}},
        },
    },
    {
        "name": "get_scenario_history",
        "description": (
            "List past scenario definitions stored in the database (survives server restarts). "
            "Use this when the operator asks about past/previous scenarios."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "factory_id": {"type": "string", "description": "Optional filter by factory"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
        },
    },
    {
        "name": "get_scenario_runs",
        "description": (
            "List past scenario run results from the database (survives server restarts). "
            "Includes run_id, status, execution_mode, residual_risk, failure_reason and timestamps. "
            "Use this when the operator asks about past events, previous runs, or execution history."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "factory_id": {"type": "string", "description": "Optional filter by factory"},
                "scenario_id": {"type": "string", "description": "Optional filter by scenario"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
        },
    },
    {
        "name": "get_scenario_run_detail",
        "description": (
            "Fetch the full result of a specific scenario run from the database, including "
            "recommendation, causal_paths, activated_rules, and pipeline metadata. "
            "Use after get_scenario_runs to drill into a specific run."
        ),
        "parameters": {
            "type": "object",
            "properties": {"run_id": {"type": "string", "description": "The run ID to fetch"}},
            "required": ["run_id"],
        },
    },
    {
        "name": "get_recent_events",
        "description": (
            "List recent safety events (sensor readings, worker detections, permit changes, "
            "model predictions) from the persistent event store. Survives server restarts. "
            "Use this when the operator asks about recent or past safety events."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max results (default 20)"},
                "zone_id": {"type": "string", "description": "Optional filter by zone"},
                "event_type": {"type": "string", "description": "Optional filter by event type"},
            },
        },
    },
    {
        "name": "get_osha_prior",
        "description": "Look up the historical OSHA base rate and severity weight for a hazard type (e.g. 'toxic_gas_exposure').",
        "parameters": {
            "type": "object",
            "properties": {"hazard_type": {"type": "string"}},
            "required": ["hazard_type"],
        },
    },
]

# name -> (is_async, arg names in declared order) is not needed; dispatch is
# done by kwargs in agent_service.py via getattr(toolkit, name)(**args).
ALLOWED_TOOL_NAMES: frozenset[str] = frozenset(d["name"] for d in TOOL_DECLARATIONS)

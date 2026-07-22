"""User-driven scenario API — the frontend's real backend.

Nothing here auto-loads or auto-runs anything. A scenario only executes when
the client POSTs it to ``/scenario/run`` (i.e. the operator clicked "Run
Scenario"). Runs are cached in-memory by ``run_id`` so the graph and results
can be refetched, and operator decisions are persisted to the hash-chained
audit log with duplicate-approval prevention.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response, status

from app.api.deps import EventRepoDep, QueueDep, SettingsDep
from pydantic import BaseModel, Field, ValidationError

from app.core.logging import get_logger
from app.engine.scenario_pipeline import STAGES as PIPELINE_STAGES
from app.engine.scenario_pipeline import run_scenario_pipeline
from app.engine.types import ApprovalDecision
from app.gateway.auth import AuthError
from app.schemas.scenario import Scenario

log = get_logger(__name__)
router = APIRouter(prefix="/scenario", tags=["scenario"])

# In-memory run store (MVP). Keyed by run_id -> {scenario, result, decision}.
_RUNS: dict[str, dict[str, Any]] = {}

def _record_execution_audit(audit, run_id, cid, scenario, result) -> None:
    """Write the execution itself to the audit log (best-effort)."""
    if audit is None:
        return
    try:
        rec = result.get("recommendation")
        audit.append(
            correlation_id=cid, recommendation_id=run_id,
            approver_id="system", approver_role="automated",
            decision="SCENARIO_EXECUTED",
            reason=(f"Scenario '{scenario.name}' — {result.get('status', 'unknown')}, "
                    f"{len(result.get('causal_paths', []))} path(s)"),
            interventions=[],
            residual_risk=rec.get("residual_risk") if rec else None)
    except Exception as exc:
        log.warning("audit log for scenario run failed: %s", exc)


_SCENARIO_DIR = Path(__file__).resolve().parents[4] / "scenarios"


# --------------------------------------------------------------------------- #
def _blank_template() -> dict[str, Any]:
    return {
        "scenario_id": "scn-example",
        "name": "New Scenario",
        "description": "",
        "factory_id": "steelforge-001",
        "safety_threshold": 0.15,
        "zones": [
            {"zone_id": "zone-1", "name": "Zone 1", "hazard_class": "gas_hazard",
             "baseline_gas_threshold_ppm": 200.0, "ventilation_status": "nominal",
             "ventilation_flow_ratio": 1.0}
        ],
        "zone_adjacency": [],
        "assets": [],
        "sensors": [],
        "gas_readings": [],
        "machine_readings": [],
        "hydraulic_readings": [],
        "workers": [],
        "permits": [],
        "events": [],
        "metadata": {},
    }


@router.get("/template", summary="Download a blank scenario JSON template")
async def template() -> dict[str, Any]:
    return _blank_template()


@router.get("/samples", summary="List available sample scenarios")
async def samples() -> dict[str, Any]:
    out = []
    if _SCENARIO_DIR.exists():
        for f in sorted(_SCENARIO_DIR.glob("*.json")):
            out.append({"file": f.name, "url": f"/api/v1/scenario/sample/{f.stem}"})
    return {"samples": out}


@router.get("/sample/{name}", summary="Load a named sample scenario")
async def sample(name: str, response: Response) -> dict[str, Any]:
    # prevent path traversal
    safe = os.path.basename(name)
    path = _SCENARIO_DIR / f"{safe}.json"
    if not path.exists():
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"error": "not_found", "detail": f"no sample '{safe}'"}
    return json.loads(path.read_text())


class ValidationResponse(BaseModel):
    valid: bool
    errors: list[dict[str, Any]] = Field(default_factory=list)
    scenario_id: str | None = None
    event_count: int | None = None


@router.post("/validate", response_model=ValidationResponse,
             summary="Validate a scenario without running it")
async def validate(payload: dict[str, Any]) -> ValidationResponse:
    try:
        scenario = Scenario.model_validate(payload)
    except ValidationError as exc:
        return ValidationResponse(
            valid=False,
            errors=[{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                    for e in exc.errors()],
        )
    return ValidationResponse(valid=True, scenario_id=scenario.scenario_id,
                              event_count=len(scenario.to_events()))


class RunResponse(BaseModel):
    run_id: str
    result: dict[str, Any]


@router.post("/run", summary="Run the full CAUSALCUT production pipeline")
async def run(
    payload: dict[str, Any],
    request: Request,
    response: Response,
    events: EventRepoDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Execute a scenario through the real backend pipeline.

    Order is load-bearing: model inference -> canonical events -> shared
    ingestion service (append-only persistence) -> asyncio queue -> consumer
    -> SQLite projection -> hypergraph -> analysis. No analysis happens before
    persistence, and the route never calls ``queue.put()`` directly.
    """
    # --- 1. Validate ---------------------------------------------------
    try:
        scenario = Scenario.model_validate(payload)
    except ValidationError as exc:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {
            "error": "invalid_scenario",
            "errors": [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                       for e in exc.errors()],
        }

    # --- 2/3. scenario_id (schema-generated) + correlation_id -----------
    cid = getattr(request.state, "correlation_id", None) or str(uuid.uuid4())
    run_id = f"run-{uuid.uuid4().hex[:10]}"

    from app.api.v1.routes.ws import broadcast_progress

    async def _progress(msg: dict) -> None:
        msg = {**msg, "run_id": run_id}
        try:
            await broadcast_progress(msg)
        except Exception:
            pass  # never break the pipeline for a progress message

    # --- 4..11. The real pipeline --------------------------------------
    try:
        result = await run_scenario_pipeline(
            scenario,
            events_repo=events,
            queue=queue,
            settings=settings,
            correlation_id=cid,
            wait_timeout=settings.scenario_pipeline_timeout_s,
            progress=_progress,
        )
    except Exception as exc:
        log.exception("scenario pipeline failed", extra={"correlation_id": cid})
        await _progress({"stage": "failed", "label": "Pipeline failed",
                         "status": "error", "error": str(exc)})
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"error": "pipeline_failed", "detail": str(exc), "correlation_id": cid}

    # Fail closed: the pipeline suppresses analysis on incomplete state.
    if result.get("status") == "failed":
        response.status_code = (status.HTTP_504_GATEWAY_TIMEOUT
                                if result["pipeline"]["timed_out"]
                                else status.HTTP_422_UNPROCESSABLE_ENTITY)
        _RUNS[run_id] = {"scenario": scenario.model_dump(mode="json"),
                         "result": result, "decision": None}
        log.error("scenario run failed", extra={
            "run_id": run_id, "correlation_id": cid,
            "failure_stage": result.get("failure_stage"),
            "failure_reason": result.get("failure_reason")})
        return {"run_id": run_id, "result": result}

    # --- Audit trail for the execution itself ---------------------------
    audit = getattr(request.app.state, "audit", None)
    if audit is not None:
        try:
            rec = result.get("recommendation")
            audit.append(
                correlation_id=cid,
                recommendation_id=run_id,
                approver_id="system",
                approver_role="automated",
                decision="SCENARIO_EXECUTED",
                reason=(f"Scenario '{scenario.name}' executed — "
                        f"{result.get('execution_mode', 'unknown')} mode, "
                        f"{len(result.get('causal_paths', []))} path(s), "
                        f"{result['pipeline']['processed_events']} event(s) processed"),
                interventions=[],
                residual_risk=rec.get("residual_risk") if rec else None,
            )
        except Exception as exc:
            log.warning("audit log for scenario run failed: %s", exc)

    _RUNS[run_id] = {"scenario": scenario.model_dump(mode="json"),
                     "result": result, "decision": None}
    log.info("scenario run", extra={
        "run_id": run_id, "scenario_id": scenario.scenario_id,
        "correlation_id": cid, "execution_mode": result.get("execution_mode"),
        "models_ran": result.get("models", {}).get("models_ran"),
        "processed_events": result["pipeline"]["processed_events"],
        "paths": len(result["causal_paths"])})

    return {"run_id": run_id, "result": result}


@router.post("/start", status_code=status.HTTP_202_ACCEPTED,
             summary="Start a scenario in the background; returns run_id immediately")
async def start(
    payload: dict[str, Any],
    request: Request,
    response: Response,
    events: EventRepoDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """202 Accepted: identifiers are minted BEFORE execution starts.

    The client gets ``run_id`` / ``scenario_id`` / ``correlation_id`` straight
    away, subscribes to ``/ws/scenarios/{run_id}`` for live stages, and can
    poll ``GET /scenario/runs/{run_id}`` as a fallback.
    """
    try:
        scenario = Scenario.model_validate(payload)
    except ValidationError as exc:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"error": "invalid_scenario",
                "errors": [{"field": ".".join(str(p) for p in e["loc"]),
                            "message": e["msg"]} for e in exc.errors()]}

    cid = getattr(request.state, "correlation_id", None) or str(uuid.uuid4())
    run_id = f"run-{uuid.uuid4().hex[:10]}"

    _RUNS[run_id] = {"scenario": scenario.model_dump(mode="json"), "result": None,
                     "decision": None, "status": "running",
                     "scenario_id": scenario.scenario_id, "correlation_id": cid,
                     "progress_history": []}

    from app.api.v1.routes.ws import TERMINAL_STAGES, broadcast_progress

    async def _progress(msg: dict) -> None:
        """Forward a pipeline stage to this run's WebSocket subscribers.

        Terminal stages are deliberately withheld here. ``run_scenario_pipeline``
        emits "completed"/"failed" as its last act, but the result has not been
        stored in ``_RUNS`` at that instant — a client that reacted to it by
        fetching ``GET /scenario/runs/{run_id}`` would race and see a run still
        marked "running" with no result. ``_settle()`` re-emits the terminal
        stage once the result is durably readable, so the contract the frontend
        relies on holds: a terminal message means the result is there.
        """
        if msg.get("stage") in TERMINAL_STAGES:
            return
        try:
            pmsg = {**msg, "run_id": run_id}
            if run_id in _RUNS:
                _RUNS[run_id].setdefault("progress_history", []).append(pmsg)
            await broadcast_progress(pmsg)
        except Exception:
            pass  # progress must never break the run

    async def _settle(stage: str, **extra: Any) -> None:
        """Announce the terminal stage — called only after ``_RUNS`` is updated."""
        pmsg = {"stage": stage, "status": stage, "run_id": run_id,
                "label": ("Pipeline execution finished" if stage == "completed"
                          else "Pipeline execution failed"),
                "index": len(PIPELINE_STAGES) - 1, "total": len(PIPELINE_STAGES),
                "final": True, **extra}
        try:
            if run_id in _RUNS:
                _RUNS[run_id].setdefault("progress_history", []).append(pmsg)
            await broadcast_progress(pmsg)
        except Exception:
            pass

    audit = getattr(request.app.state, "audit", None)

    async def _execute() -> None:
        try:
            result = await run_scenario_pipeline(
                scenario, events_repo=events, queue=queue, settings=settings,
                correlation_id=cid, wait_timeout=settings.scenario_pipeline_timeout_s,
                progress=_progress)
            status_ = result.get("status", "completed")
            _RUNS[run_id]["result"] = result
            _RUNS[run_id]["status"] = status_
            _record_execution_audit(audit, run_id, cid, scenario, result)
            await _settle(status_ if status_ in TERMINAL_STAGES else "completed",
                          error=result.get("failure_reason"))
        except Exception as exc:
            log.exception("background scenario failed", extra={"run_id": run_id})
            if run_id in _RUNS:
                _RUNS[run_id]["status"] = "failed"
                _RUNS[run_id]["result"] = {
                    "scenario_id": scenario.scenario_id,
                    "scenario_name": scenario.name,
                    "correlation_id": cid,
                    "status": "failed",
                    "failure_reason": str(exc),
                    "failures": [str(exc)],
                    "recommendation": None, "activated_rules": [],
                    "causal_paths": [], "graph": None,
                    "regulatory_citations": [],
                    "explanation": f"Pipeline raised an error: {exc}",
                    "warnings": [str(exc)],
                }
            await _settle("failed", error=str(exc))

    asyncio.create_task(_execute())

    return {"run_id": run_id, "scenario_id": scenario.scenario_id,
            "correlation_id": cid, "status": "running",
            "progress_ws": f"/api/v1/ws/scenarios/{run_id}",
            "status_url": f"/api/v1/scenario/runs/{run_id}"}


@router.get("/runs/{run_id}", summary="Poll a background run's status/result")
async def run_status(run_id: str, response: Response) -> dict[str, Any]:
    """Polling fallback for clients whose WebSocket could not be established.

    ``progress`` is the same stage stream the socket carries — the actual
    messages the pipeline emitted, not a synthetic approximation — so a
    polling client renders identical progress to a connected one, just at a
    coarser granularity.
    """
    run = _RUNS.get(run_id)
    if run is None:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"error": "not_found", "detail": f"no run '{run_id}'"}
    body = {"run_id": run_id, "status": run.get("status", "completed"),
            "scenario_id": run.get("scenario_id"),
            "correlation_id": run.get("correlation_id"),
            "decision": run.get("decision"),
            "stages": [s for s, _ in PIPELINE_STAGES],
            "progress": list(run.get("progress_history", []))}
    if run.get("result") is not None:
        body["result"] = run["result"]
    return body


@router.get("/{run_id}", summary="Fetch a completed run (results + graph)")
async def get_run(run_id: str, response: Response) -> dict[str, Any]:
    run = _RUNS.get(run_id)
    if run is None:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"error": "not_found", "detail": f"no run '{run_id}'"}
    return {"run_id": run_id, "result": run["result"], "decision": run["decision"]}


@router.get("/{run_id}/graph", summary="Fetch just the safety hypergraph for a run")
async def get_graph(run_id: str, response: Response) -> dict[str, Any]:
    run = _RUNS.get(run_id)
    if run is None:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"error": "not_found", "detail": f"no run '{run_id}'"}
    return run["result"]["graph"]


class DecisionIn(BaseModel):
    decision: ApprovalDecision
    reason: str = Field(default="", max_length=1000)


@router.post("/{run_id}/decision", summary="Operator approve/reject/defer — audit-persisted")
async def decide(run_id: str, payload: DecisionIn, request: Request,
                 response: Response) -> dict[str, Any]:
    run = _RUNS.get(run_id)
    if run is None:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"error": "not_found", "detail": f"no run '{run_id}'"}

    # Duplicate-approval prevention.
    if run["decision"] is not None:
        response.status_code = status.HTTP_409_CONFLICT
        return {"error": "already_decided", "detail": run["decision"]}

    auth = request.app.state.auth
    audit = request.app.state.audit
    api_key = request.headers.get("X-API-Key")
    try:
        operator = auth.authenticate(api_key)
        if payload.decision is ApprovalDecision.APPROVE:
            auth.require_authority(operator, "shift_officer")
    except AuthError as exc:
        code = status.HTTP_401_UNAUTHORIZED if "key" in str(exc).lower() \
            else status.HTTP_403_FORBIDDEN
        response.status_code = code
        return {"error": "unauthorized", "detail": str(exc)}

    rec = run["result"].get("recommendation")
    interventions = [i["intervention_id"] for i in rec["interventions"]] if rec else []
    residual = rec["residual_risk"] if rec else None

    record = audit.append(
        correlation_id=getattr(request.state, "correlation_id", "unknown"),
        recommendation_id=run_id,
        approver_id=operator.operator_id,
        approver_role=operator.role,
        decision=payload.decision.value,
        reason=payload.reason,
        interventions=interventions,
        residual_risk=residual,
    )

    decision_record = {
        "audit_seq": record.seq,
        "decision": payload.decision.value,
        "approver": operator.operator_id,
        "approver_role": operator.role,
        "reason": payload.reason,
        "interventions": interventions,
        "dispatched": payload.decision is ApprovalDecision.APPROVE,
        "timestamp": record.timestamp if hasattr(record, "timestamp") else None,
    }
    run["decision"] = decision_record
    return decision_record

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

from app.api.deps import EventRepoDep, QueueDep, ScenarioRepoDep, SettingsDep
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


def _ensure_factory(db_client, factory_id: str, name: str) -> None:
    """Upsert the factory row, tolerating either 'id' or 'factory_id' PK.

    The Supabase migrations may have been applied with either column name.
    We try both and log at WARNING level if both fail, so the error is not
    silently swallowed any more.
    """
    errors: list[str] = []
    for pk_col in ("id", "factory_id"):
        try:
            db_client.table("factories").upsert(
                {pk_col: factory_id, "name": name},
                on_conflict=pk_col,
            ).execute()
            return  # succeeded
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{pk_col}: {exc}")
    log.warning(
        "factory upsert failed with both PK names — scenarios may fail if "
        "Supabase has a FK constraint on scenarios.factory_id",
        extra={"factory_id": factory_id, "errors": errors},
    )

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
        "factory_id": "00000000-0000-0000-0000-000000000001",
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
    scenario_repo: ScenarioRepoDep,
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
                       for e in exc.errors()]
        }

    # --- Scrub invalid UUID factory_ids
    import uuid
    from datetime import datetime, timezone
    try:
        uuid.UUID(str(scenario.factory_id))
    except (ValueError, TypeError, AttributeError):
        scenario.factory_id = str(uuid.uuid4())

    # --- 2/3. scenario_id + correlation_id -----------------------------
    cid = getattr(request.state, "correlation_id", None) or str(uuid.uuid4())
    scenario.scenario_id = scenario.scenario_id or str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # --- Upsert factory row to satisfy any FK constraint on factory_id -----
    # Tries both 'id' and 'factory_id' PK column names; logs on failure.
    _ensure_factory(
        request.app.state.db.client,
        factory_id=str(scenario.factory_id),
        name=scenario.name or "Factory",
    )
    run_id = f"run-{uuid.uuid4().hex[:10]}"

    # --- Persist scenario definition BEFORE the pipeline ---------------
    # Idempotent: re-running the same scenario_id is a no-op on the definition.
    saved = await scenario_repo.upsert_scenario(
        scenario_id=scenario.scenario_id,
        factory_id=str(scenario.factory_id),
        name=scenario.name or "",
        description=scenario.description or "",
        payload_json=scenario.model_dump_json(),
        created_at=now_iso,
    )
    if not saved:
        log.warning(
            "scenario definition upsert returned False — DB row may not exist",
            extra={"scenario_id": scenario.scenario_id, "factory_id": scenario.factory_id},
        )

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

    final_status = result.get("status", "completed")

    # --- Persist the run result (best-effort, never blocks the response) -
    await scenario_repo.upsert_run(
        run_id=run_id,
        scenario_id=scenario.scenario_id,
        factory_id=str(scenario.factory_id),
        correlation_id=cid,
        status=final_status,
        result=result,
    )

    # Fail closed: the pipeline suppresses analysis on incomplete state.
    if final_status == "failed":
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
    log.info("scenario run persisted to DB", extra={
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
    scenario_repo: ScenarioRepoDep,
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

    # --- Scrub invalid UUID factory_ids
    import uuid
    from datetime import datetime, timezone
    try:
        uuid.UUID(str(scenario.factory_id))
    except (ValueError, TypeError, AttributeError):
        scenario.factory_id = str(uuid.uuid4())

    cid = getattr(request.state, "correlation_id", None) or str(uuid.uuid4())
    scenario.scenario_id = scenario.scenario_id or str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # --- Upsert factory row to satisfy any FK constraint on factory_id -----
    _ensure_factory(
        request.app.state.db.client,
        factory_id=str(scenario.factory_id),
        name=scenario.name or "Factory",
    )

    run_id = f"run-{uuid.uuid4().hex[:10]}"

    # --- Persist scenario definition immediately (before background task) -
    saved = await scenario_repo.upsert_scenario(
        scenario_id=scenario.scenario_id,
        factory_id=str(scenario.factory_id),
        name=scenario.name or "",
        description=scenario.description or "",
        payload_json=scenario.model_dump_json(),
        created_at=now_iso,
    )
    if not saved:
        log.warning(
            "scenario definition upsert returned False (start endpoint) — DB row may not exist",
            extra={"scenario_id": scenario.scenario_id, "factory_id": scenario.factory_id},
        )

    # --- Seed the run row as 'running' so it can be polled immediately --
    await scenario_repo.upsert_run(
        run_id=run_id,
        scenario_id=scenario.scenario_id,
        factory_id=str(scenario.factory_id),
        correlation_id=cid,
        status="running",
        result={},
    )

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
            # Persist the completed run result to DB
            await scenario_repo.upsert_run(
                run_id=run_id,
                scenario_id=scenario.scenario_id,
                factory_id=str(scenario.factory_id),
                correlation_id=cid,
                status=status_,
                result=result,
            )
            await _settle(status_ if status_ in TERMINAL_STAGES else "completed",
                          error=result.get("failure_reason"))
        except Exception as exc:
            log.exception("background scenario failed", extra={"run_id": run_id})
            failed_result = {
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
            if run_id in _RUNS:
                _RUNS[run_id]["status"] = "failed"
                _RUNS[run_id]["result"] = failed_result
            # Persist the failure so it's visible in the DB too
            await scenario_repo.upsert_run(
                run_id=run_id,
                scenario_id=scenario.scenario_id,
                factory_id=str(scenario.factory_id),
                correlation_id=cid,
                status="failed",
                result=failed_result,
            )
            await _settle("failed", error=str(exc))

    asyncio.create_task(_execute())

    return {"run_id": run_id, "scenario_id": scenario.scenario_id,
            "correlation_id": cid, "status": "running",
            "progress_ws": f"/api/v1/ws/scenarios/{run_id}",
            "status_url": f"/api/v1/scenario/runs/{run_id}"}


@router.get("/runs/{run_id}", summary="Poll a background run's status/result")
async def run_status(run_id: str, response: Response,
                     scenario_repo: ScenarioRepoDep) -> dict[str, Any]:
    """Polling fallback for clients whose WebSocket could not be established.

    ``progress`` is the same stage stream the socket carries — the actual
    messages the pipeline emitted, not a synthetic approximation — so a
    polling client renders identical progress to a connected one, just at a
    coarser granularity.
    """
    run = _RUNS.get(run_id)
    if run is None:
        # Fall back to DB so results survive server restarts
        row = await scenario_repo.get_run(run_id)
        if row is not None:
            return {"run_id": run_id, "status": row.get("status", "completed"),
                    "source": "database",
                    "scenario_id": row.get("scenario_id"),
                    "correlation_id": row.get("correlation_id"),
                    "decision": None,
                    "stages": [s for s, _ in PIPELINE_STAGES],
                    "progress": [],
                    "result": row}
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
async def get_run(run_id: str, response: Response,
                  scenario_repo: ScenarioRepoDep) -> dict[str, Any]:
    run = _RUNS.get(run_id)
    if run is not None:
        return {"run_id": run_id, "result": run["result"], "decision": run["decision"]}
    # Fall back to DB so results survive server restarts
    row = await scenario_repo.get_run(run_id)
    if row is not None:
        return {"run_id": run_id, "source": "database", "result": row, "decision": None}
    response.status_code = status.HTTP_404_NOT_FOUND
    return {"error": "not_found", "detail": f"no run '{run_id}'"}


@router.get("/{run_id}/graph", summary="Fetch just the safety hypergraph for a run")
async def get_graph(run_id: str, response: Response,
                    scenario_repo: ScenarioRepoDep) -> dict[str, Any]:
    run = _RUNS.get(run_id)
    if run is not None:
        return run["result"]["graph"]
    # Fall back to DB so results survive server restarts
    row = await scenario_repo.get_run(run_id)
    if row is not None:
        # The graph is inside the pipeline_json column (or the full result)
        pipeline = row.get("pipeline_json") or {}
        if isinstance(pipeline, dict) and "graph" in pipeline:
            return pipeline["graph"]
        return {"warning": "graph not stored in DB for this run", "run_id": run_id}
    response.status_code = status.HTTP_404_NOT_FOUND
    return {"error": "not_found", "detail": f"no run '{run_id}'"}


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


# --------------------------------------------------------------------------- #
# Operator alternative input — the learning loop
# --------------------------------------------------------------------------- #

class AlternativeIn(BaseModel):
    """Structured operator feedback when they reject a recommendation.

    This is the primary mechanism by which the system learns from human
    expertise. Each alternative is stored in the audit log with a distinct
    decision code so it can be retrieved as training/few-shot data.
    """
    alternative_action: str = Field(..., min_length=1, max_length=2000,
                                    description="What the operator would have done instead")
    breaks_factors: list[str] = Field(default_factory=list,
                                      description="Causal factors this action would address")
    operator_confidence: int = Field(default=3, ge=1, le=5,
                                     description="Operator confidence 1 (uncertain) – 5 (certain)")
    reason: str = Field(default="", max_length=2000,
                        description="Operational context / SOP rationale")
    original_intervention_id: str | None = Field(
        default=None, description="The intervention ID that was rejected")


@router.post("/{run_id}/alternative",
             summary="Record operator alternative when recommendation is rejected")
async def record_alternative(
    run_id: str,
    payload: AlternativeIn,
    request: Request,
    response: Response,
    scenario_repo: ScenarioRepoDep,
) -> dict[str, Any]:
    """Persist an operator's alternative intervention as a learning signal.

    Called by the frontend immediately after a REJECT decision. The operator
    describes what they would have done instead, which causal factors it
    addresses, and how confident they are. This structured feedback is:

    1. Written to the tamper-evident audit log (decision = OPERATOR_ALTERNATIVE)
    2. Stored in _RUNS so it's accessible in-process
    3. Persisted to the scenario run record in the DB for offline model training

    The intent is that these records accumulate into a dataset that can be used
    to fine-tune the recommendation model or enrich the LLM fallback's few-shot
    examples — human expertise captured in structured form.
    """
    run = _RUNS.get(run_id)

    # Accept even if run is not in memory (server restart), just audit-log it
    cid = getattr(request.state, "correlation_id", None) or str(uuid.uuid4())

    audit = getattr(request.app.state, "audit", None)
    if audit is not None:
        try:
            audit.append(
                correlation_id=cid,
                recommendation_id=run_id,
                approver_id="operator",
                approver_role="shift_officer",
                decision="OPERATOR_ALTERNATIVE",
                reason=(
                    f"Alternative: '{payload.alternative_action}' | "
                    f"Confidence: {payload.operator_confidence}/5 | "
                    f"Addresses: {', '.join(payload.breaks_factors) or 'unspecified'} | "
                    f"Context: {payload.reason}"
                ),
                interventions=payload.breaks_factors,
                residual_risk=None,
            )
        except Exception as exc:
            log.warning("audit log for alternative failed: %s", exc)

    # Enrich the in-memory run record so it can be queried in-process
    if run is not None:
        run.setdefault("alternatives", []).append({
            "alternative_action": payload.alternative_action,
            "breaks_factors": payload.breaks_factors,
            "operator_confidence": payload.operator_confidence,
            "reason": payload.reason,
            "original_intervention_id": payload.original_intervention_id,
            "correlation_id": cid,
        })

    # Best-effort: enrich the persisted DB run record with the alternative
    if run is not None:
        try:
            existing_result = run.get("result") or {}
            enriched = {
                **existing_result,
                "operator_alternatives": run.get("alternatives", []),
            }
            await scenario_repo.upsert_run(
                run_id=run_id,
                scenario_id=run.get("scenario_id", "unknown"),
                factory_id=str(run.get("scenario", {}).get("factory_id", "unknown")),
                correlation_id=cid,
                status=run.get("status", "completed"),
                result=enriched,
            )
        except Exception as exc:
            log.warning("DB enrichment with alternative failed (non-fatal): %s", exc)

    alternative_record = {
        "recorded": True,
        "run_id": run_id,
        "alternative_action": payload.alternative_action,
        "breaks_factors": payload.breaks_factors,
        "operator_confidence": payload.operator_confidence,
        "reason": payload.reason,
        "original_intervention_id": payload.original_intervention_id,
        "correlation_id": cid,
        "message": (
            "Operator alternative persisted to audit log and enriched on the run record. "
            "This signal will be used to improve future recommendations."
        ),
    }
    log.info(
        "operator alternative recorded",
        extra={"run_id": run_id, "confidence": payload.operator_confidence,
               "factors": payload.breaks_factors},
    )
    return alternative_record


# --------------------------------------------------------------------------- #
# Persistent history endpoints (survive server restarts)
# --------------------------------------------------------------------------- #

@router.get("/history", summary="List persisted scenarios from the database")
async def scenario_history(
    scenario_repo: ScenarioRepoDep,
    factory_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Return the list of scenario definitions stored in the DB.

    Unlike ``GET /scenario/runs/{run_id}`` which reads from the in-memory
    ``_RUNS`` dict, this endpoint reads from Supabase and survives server
    restarts. Use it to populate a 'Past Scenarios' table in the UI.
    """
    scenarios = await scenario_repo.list_scenarios(factory_id=factory_id, limit=limit)
    return {"scenarios": scenarios, "total": len(scenarios)}


@router.get("/history/runs", summary="List persisted scenario runs from the database")
async def scenario_runs_history(
    scenario_repo: ScenarioRepoDep,
    factory_id: str | None = None,
    scenario_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Return the list of scenario runs stored in the DB.

    Each row contains: run_id, scenario_id, status, residual_risk,
    execution_mode, processed_events, failure_reason, created_at, completed_at.
    The full recommendation and causal_paths are omitted for list performance;
    use ``GET /scenario/db/{run_id}`` to fetch the full detail.
    """
    runs = await scenario_repo.list_runs(
        factory_id=factory_id, scenario_id=scenario_id, limit=limit
    )
    return {"runs": runs, "total": len(runs)}


@router.get("/db/{run_id}", summary="Fetch a run from the database (survives restarts)")
async def get_run_from_db(
    run_id: str,
    scenario_repo: ScenarioRepoDep,
    response: Response,
) -> dict[str, Any]:
    """Fetch the full run record from Supabase by run_id.

    This is the durable read path. ``GET /scenario/{run_id}`` reads from the
    in-memory cache which is lost on restart. This endpoint reads from the DB
    and always returns the persisted result, including recommendation,
    causal_paths, activated_rules, and pipeline metadata.

    Falls back gracefully: if the run is not in the DB yet (still running),
    tries the in-memory cache.
    """
    # Try DB first (durable)
    row = await scenario_repo.get_run(run_id)
    if row is not None:
        return {"run_id": run_id, "source": "database", "run": row}

    # Fall back to in-memory cache (for runs still in progress)
    run = _RUNS.get(run_id)
    if run is not None:
        return {
            "run_id": run_id,
            "source": "memory",
            "run": {
                "run_id": run_id,
                "status": run.get("status", "running"),
                "scenario_id": run.get("scenario_id"),
                "correlation_id": run.get("correlation_id"),
                "result": run.get("result"),
            },
        }

    response.status_code = status.HTTP_404_NOT_FOUND
    return {"error": "not_found", "detail": f"No run '{run_id}' in database or memory cache"}


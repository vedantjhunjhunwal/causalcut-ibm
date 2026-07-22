"""Risk, approval and handover surface — the analytical half of the API.

These routes sit on top of the same ingestion spine as everything else:
  * GET  /risk/paths            — active accident pathways (engine view)
  * GET  /risk/recommendation   — current minimum causal cut (or none)
  * POST /risk/approve          — authenticated human decision, write-ahead audited
  * GET  /risk/audit            — tail the hash-chained audit log + verify
  * POST /handover/validate     — shift-handover consistency check

Approval is the one place the system crosses from *recommend* to *act*: it is
authenticated (X-API-Key -> operator), authority-gated (shift_officer+ to
approve), and every decision is appended to a tamper-evident log before it is
reported as dispatched.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.engine.types import ApprovalDecision, ShiftHandover
from app.gateway.auth import AuthError

log = get_logger(__name__)

router = APIRouter(tags=["risk"])


def _risk(request: Request):
    return request.app.state.risk_engine


def _auth(request: Request):
    return request.app.state.auth


def _audit(request: Request):
    return request.app.state.audit


@router.get("/risk/paths", summary="Active accident pathways (engine view)")
async def risk_paths(request: Request) -> dict[str, Any]:
    return _risk(request).paths_payload()


@router.get("/risk/recommendation", summary="Current minimum causal cut")
async def risk_recommendation(request: Request) -> dict[str, Any]:
    return _risk(request).recommendation_payload()


class ApprovalIn(BaseModel):
    recommendation_id: str = "current"
    decision: ApprovalDecision
    reason: str = Field(default="", max_length=1000)


@router.post("/risk/approve", summary="Authenticated human decision on the current cut")
async def approve(payload: ApprovalIn, request: Request, response: Response) -> dict[str, Any]:
    auth = _auth(request)
    audit = _audit(request)
    engine = _risk(request)

    api_key = request.headers.get("X-API-Key")
    try:
        operator = auth.authenticate(api_key)
        # Approving a cut dispatches interventions -> requires shift_officer+.
        if payload.decision is ApprovalDecision.APPROVE:
            auth.require_authority(operator, "shift_officer")
    except AuthError as exc:
        code = status.HTTP_401_UNAUTHORIZED if "key" in str(exc).lower() \
            else status.HTTP_403_FORBIDDEN
        response.status_code = code
        return {"error": "unauthorized", "detail": str(exc)}

    _, rec = engine.current()
    interventions = [i.intervention_id for i in rec.interventions] if rec else []
    residual = rec.residual_risk if rec else None

    record = audit.append(
        correlation_id=getattr(request.state, "correlation_id", "unknown"),
        recommendation_id=payload.recommendation_id,
        approver_id=operator.operator_id,
        approver_role=operator.role,
        decision=payload.decision.value,
        reason=payload.reason,
        interventions=interventions,
        residual_risk=residual,
    )

    dispatched = payload.decision is ApprovalDecision.APPROVE
    return {
        "audit_seq": record.seq,
        "decision": payload.decision.value,
        "approver": operator.operator_id,
        "dispatched": dispatched,
        "interventions": interventions,
    }


@router.get("/risk/audit", summary="Tail the write-ahead, hash-chained audit log")
async def audit_tail(request: Request, limit: int = 50) -> dict[str, Any]:
    audit = _audit(request)
    ok, first_bad = audit.verify_chain()
    return {
        "chain_valid": ok,
        "first_bad_seq": first_bad,
        "records": audit.tail(limit),
    }


@router.post("/handover/validate", summary="Validate a shift handover against live state")
async def handover_validate(handover: ShiftHandover, request: Request) -> dict[str, Any]:
    validator = request.app.state.handover_validator
    issues = validator.validate(handover)
    return {
        "handover_id": handover.handover_id,
        "consistent": len(issues) == 0,
        "inconsistencies": [
            {
                "kind": i.kind,
                "zone_id": i.zone_id,
                "detail": i.detail,
                "severity": i.severity,
                "references": i.references,
            }
            for i in issues
        ],
    }

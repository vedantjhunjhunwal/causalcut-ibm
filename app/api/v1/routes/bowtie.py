"""Bow-Tie API routes — G1 of the Gap Analysis.

GET /bowtie/          — list all bow-tie definitions (one per CompoundRule)
GET /bowtie/{id}      — single bow-tie by template_id (e.g. HE-042)

These endpoints expose the formal process-safety vocabulary (threats,
preventive/mitigative barriers, top event, source reference) that sits on
top of the existing CompoundRule engine. No detection logic is here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from typing import Any

router = APIRouter(prefix="/bowtie", tags=["bowtie"])


def _registry(request: Request):
    return request.app.state.bowtie_registry


@router.get(
    "/",
    summary="List all bow-tie definitions",
    description=(
        "Returns the full bow-tie formalism view of every compound rule: "
        "threats, preventive barriers, top event, mitigative barriers, "
        "consequences, and HAZOP/OISD source reference."
    ),
)
async def list_bowties(request: Request) -> dict[str, Any]:
    reg = _registry(request)
    return {
        "bowties": [bt.model_dump() for bt in reg.list_all()],
        "count": len(reg),
    }


@router.get(
    "/{template_id}",
    summary="Get bow-tie by template ID",
    description=(
        "Returns the bow-tie definition for a specific compound rule, "
        "e.g. HE-042 (coke-oven flash-fire), HE-TOXIC-EXPOSURE, etc."
    ),
)
async def get_bowtie(template_id: str, request: Request) -> dict[str, Any]:
    reg = _registry(request)
    bt = reg.get(template_id)
    if bt is None:
        raise HTTPException(
            status_code=404,
            detail=f"No bow-tie found for template_id '{template_id}'. "
                   f"Available: {[b.hazard_id for b in reg.list_all()]}",
        )
    return bt.model_dump()

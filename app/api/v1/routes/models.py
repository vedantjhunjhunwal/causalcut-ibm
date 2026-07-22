"""Model inference API — thin HTTP surface over the shared model services.

These routes contain NO model-loading or preprocessing logic; they delegate to
``app.services.model_service`` singletons, the same objects the scenario
orchestrator uses. Responses are the stable ``ModelResponse`` envelope.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from app.services.model_service import (
    InvalidFeaturesError,
    ModelUnavailableError,
    get_registry,
)

router = APIRouter(prefix="/models", tags=["models"])


def _cid(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unknown")


# ------------------------------------------------------------------ health ---
@router.get("/health", summary="Model layer liveness")
async def health() -> dict[str, Any]:
    return {"status": "ok", "layer": "model-inference"}


@router.get("/status", summary="Per-model load status + artifact + mode")
async def model_status() -> dict[str, Any]:
    return get_registry().status_all()


@router.get("/readiness", summary="Which models can serve real inference")
async def readiness() -> dict[str, Any]:
    return get_registry().readiness()


# -------------------------------------------------------------------- gas ---
class GasPredictIn(BaseModel):
    features: list[float] = Field(..., description="128-dim UCI gas sensor array "
                                  "(16 sensors x 8 features, in training order)")
    sensor_id: str = "GS-03"
    zone_id: str = "zone-1"
    scenario_id: str | None = None


@router.post("/gas/predict", summary="Gas type + drift (XGBoost + IsolationForest)")
async def gas_predict(payload: GasPredictIn, request: Request, response: Response) -> dict[str, Any]:
    try:
        r = get_registry().gas.predict(
            payload.features, sensor_id=payload.sensor_id, zone_id=payload.zone_id,
            correlation_id=_cid(request), scenario_id=payload.scenario_id)
        return r.to_dict()
    except InvalidFeaturesError as e:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"error": "invalid_features", "detail": str(e)}
    except ModelUnavailableError as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"error": "model_unavailable", "detail": str(e)}


# --------------------------------------------------------- machine failure ---
class MachinePredictIn(BaseModel):
    """AI4I machine-condition features.

    Feature order is taken from the trained artifact itself
    (``feature_names_in_``); the pipeline's MinMaxScaler + OneHotEncoder then
    apply the exact preprocessing used during training.
    """
    Type: str = Field(default="M", description="Product quality variant: L | M | H")
    Air_temperature: float = Field(description="Air temperature [K]")
    Process_temperature: float = Field(description="Process temperature [K]")
    Rotational_speed: float = Field(description="Rotational speed [rpm]")
    Torque: float = Field(description="Torque [Nm]")
    Tool_wear: float = Field(description="Tool wear [min]")
    scenario_id: str | None = None


@router.post(
    "/machine-failure/predict",
    summary="AI4I machine failure probabilities (LightGBM, calibrated)",
    response_description=(
        "Envelope with prediction{machine_failure, top_failure_mode, failure_modes, "
        "probabilities}, plus failure_modes, probabilities, confidence, model_name, "
        "model_version, latency_ms, inference_mode, degraded_reason."
    ),
)
async def machine_predict(payload: MachinePredictIn, request: Request, response: Response) -> dict[str, Any]:
    feats = payload.model_dump(exclude={"scenario_id"})
    try:
        # Shared singleton — the same object the scenario runner uses.
        r = get_registry().machine.predict(feats, correlation_id=_cid(request),
                                            scenario_id=payload.scenario_id)
        if r.inference_mode == "degraded":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return r.to_dict()
    except InvalidFeaturesError as e:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"error": "invalid_features", "detail": str(e)}


# ---------------------------------------------------------------- hydraulic ---
class HydraulicPredictIn(BaseModel):
    sensor_data: dict[str, list[float]] = Field(..., description="Per-sensor cycle arrays "
                                                "for PS1..SE (17 sensors)")
    scenario_id: str | None = None


@router.post("/hydraulic/predict", summary="Hydraulic condition (LightGBM multi-output)")
async def hydraulic_predict(payload: HydraulicPredictIn, request: Request, response: Response) -> dict[str, Any]:
    try:
        r = get_registry().hydraulic.predict(payload.sensor_data, correlation_id=_cid(request),
                                              scenario_id=payload.scenario_id)
        if r.inference_mode == "degraded":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return r.to_dict()
    except InvalidFeaturesError as e:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"error": "invalid_features", "detail": str(e)}


# ------------------------------------------------------------------ vision ---
class VisionDetectIn(BaseModel):
    image_ref: Any = Field(..., description="Image path / base64 / frame reference")
    scenario_id: str | None = None


@router.post("/vision/detect", summary="YOLOv8 person + PPE detection")
async def vision_detect(payload: VisionDetectIn, request: Request, response: Response) -> dict[str, Any]:
    r = get_registry().vision.detect(payload.image_ref, correlation_id=_cid(request),
                                     scenario_id=payload.scenario_id)
    if r.inference_mode == "degraded":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return r.to_dict()


# ---------------------------------------------------------------- tracking ---
class TrackingUpdateIn(BaseModel):
    detections: list[dict] = Field(default_factory=list)
    scenario_id: str | None = None


@router.post("/tracking/update", summary="ByteTrack worker re-identification update")
async def tracking_update(payload: TrackingUpdateIn, request: Request, response: Response) -> dict[str, Any]:
    r = get_registry().tracking.update(payload.detections, correlation_id=_cid(request),
                                       scenario_id=payload.scenario_id)
    if r.inference_mode == "degraded":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return r.to_dict()


# -------------------------------------------------------------- regulatory ---
class RegulatoryVerifyIn(BaseModel):
    actions: list[str]
    zone_context: str = ""
    scenario_id: str | None = None


@router.post("/regulatory/verify", summary="RAG compliance verification (FAISS)")
async def regulatory_verify(payload: RegulatoryVerifyIn, request: Request) -> dict[str, Any]:
    r = get_registry().regulatory.verify(payload.actions, payload.zone_context,
                                          correlation_id=_cid(request), scenario_id=payload.scenario_id)
    return r.to_dict()

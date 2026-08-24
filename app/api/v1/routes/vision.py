"""Vision pre-detection endpoint — scenario builder auto-population.

POST /api/v1/vision/detect
    Accepts an image (base64 or URL reference) and a zone_id.
    Runs YOLO PPE detection + ByteTrack person tracking.
    Returns detected workers with PPE status so the scenario builder
    can pre-fill the workers[] array without manual entry.

Design notes:
    - Reuses the EXACT same registry.vision / registry.tracking service
      calls as model_events.py so there is one inference code path.
    - Gracefully degrades: if the vision service is unavailable, returns
      inference_mode=unavailable and an empty list — the frontend falls
      back to manual entry.
    - No worker is fabricated: if YOLO finds no person, the list is empty.
    - Track IDs from ByteTrack become stable worker IDs (W-{track_id})
      that persist across frames if the user submits multiple images.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.services.model_service import get_registry

log = get_logger(__name__)
router = APIRouter(prefix="/vision", tags=["vision"])


# --------------------------------------------------------------------------- #
# Request / Response models
# --------------------------------------------------------------------------- #

class VisionDetectRequest(BaseModel):
    """Image to run through YOLO + ByteTrack before building a scenario."""
    zone_id: str = Field(
        description="Zone where this image was captured. Used to assign detected workers.",
        examples=["zone-1"],
    )
    image_b64: str | None = Field(
        default=None,
        description="Base64-encoded image (JPEG or PNG). Provide either this or image_ref.",
    )
    image_ref: str | None = Field(
        default=None,
        description="URL or filesystem reference to an image. Provide either this or image_b64.",
    )

    model_config = {"extra": "forbid"}


class DetectedWorker(BaseModel):
    """A single worker detected from YOLO + ByteTrack output."""
    worker_id: str = Field(description="Stable ID derived from ByteTrack track_id, e.g. W-3.")
    zone_id: str
    present: bool = True
    missing_ppe: list[str] = Field(
        default_factory=list,
        description="PPE items not detected on this worker (e.g. hard_hat, vest).",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Detection confidence from YOLO.")
    bbox: list[float] | None = Field(
        default=None,
        description="Bounding box [x, y, w, h] in pixel coordinates.",
    )


class VisionDetectResponse(BaseModel):
    """Detection results for use in the scenario builder workers[] pre-fill."""
    zone_id: str
    detected_workers: list[DetectedWorker]
    inference_mode: str = Field(
        description="real if YOLO ran, unavailable if model not loaded, error on failure.",
    )
    model_name: str | None = None
    model_version: str | None = None
    note: str = (
        "Detected workers are pre-filled suggestions. Review and edit before running "
        "the scenario — the model may miss workers or misclassify PPE."
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _missing_ppe_from_classes(classes: set[str]) -> list[str]:
    """Map YOLO class names to missing PPE item names."""
    missing: list[str] = []
    if "no_hat" in classes or "no_hard_hat" in classes:
        missing.append("hard_hat")
    if "no_vest" in classes or "no_safety_vest" in classes:
        missing.append("vest")
    # Fallback: person detected but no explicit hat/vest class seen
    if not missing and "person" in classes:
        if "hard_hat" not in classes and "helmet" not in classes:
            missing.append("hard_hat")
        if "safety_vest" not in classes and "vest" not in classes:
            missing.append("vest")
    return missing


def _worker_id_from_track(track_id: int | None, idx: int) -> str:
    """Produce a deterministic worker ID from a ByteTrack track_id."""
    tid = track_id if track_id is not None else (100 + idx)
    return f"W-{tid}"


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #

@router.post(
    "/detect",
    response_model=VisionDetectResponse,
    summary="Detect workers and PPE status from an image (scenario pre-fill)",
    description=(
        "Run YOLO PPE detection and ByteTrack on a single image. "
        "Returns detected workers with PPE status for pre-filling the scenario builder. "
        "If the vision model is not loaded, returns inference_mode=unavailable and "
        "an empty worker list — the client falls back to manual entry."
    ),
)
async def detect_workers(req: VisionDetectRequest) -> VisionDetectResponse:
    if not req.image_b64 and not req.image_ref:
        return VisionDetectResponse(
            zone_id=req.zone_id,
            detected_workers=[],
            inference_mode="error",
            note="Provide either image_b64 or image_ref.",
        )

    registry = get_registry()
    image_ref = (
        {"format": "base64", "data": req.image_b64}
        if req.image_b64
        else req.image_ref
    )

    # --- Step 1: YOLO detection ---
    try:
        vision_resp = registry.vision.detect(image_ref)
    except Exception as exc:
        log.warning("vision.detect failed: %s", exc)
        return VisionDetectResponse(
            zone_id=req.zone_id,
            detected_workers=[],
            inference_mode="error",
            note=f"Vision inference failed: {exc}",
        )

    if vision_resp.inference_mode != "real":
        return VisionDetectResponse(
            zone_id=req.zone_id,
            detected_workers=[],
            inference_mode=vision_resp.inference_mode or "unavailable",
            model_name=vision_resp.model_name,
            model_version=vision_resp.model_version,
            note=(
                "Vision model unavailable. "
                f"Reason: {vision_resp.degraded_reason or 'model not loaded'}. "
                "Please enter workers manually."
            ),
        )

    raw_detections: list[dict[str, Any]] = vision_resp.prediction or []
    if hasattr(raw_detections, "to_dict"):
        raw_detections = raw_detections.to_dict()
    if isinstance(raw_detections, dict):
        raw_detections = raw_detections.get("detections", [])

    # --- Step 2: ByteTrack tracking for stable IDs ---
    tracking_payload = [
        {
            "frame_id": int(d.get("frame_id", 0)),
            "bbox": d.get("bbox", [0, 0, 0, 0]),
            "class": str(d.get("class_name") or d.get("class") or "person"),
            "confidence": float(d.get("confidence", 0.9)),
        }
        for d in raw_detections
        if isinstance(d, dict) and str(
            d.get("class_name") or d.get("class") or ""
        ).lower() == "person"
    ]

    tracks: list[dict[str, Any]] = []
    if tracking_payload:
        try:
            track_resp = registry.tracking.update(tracking_payload)
            if track_resp.inference_mode == "real":
                raw_tracks = track_resp.prediction or []
                if isinstance(raw_tracks, dict):
                    raw_tracks = raw_tracks.get("tracks", [])
                tracks = [t for t in raw_tracks if isinstance(t, dict)]
        except Exception as exc:
            log.warning("tracking.update failed (falling back to detection IDs): %s", exc)
            # Fall back to using detection indices as IDs
            tracks = [
                {"track_id": 100 + i, "bbox": p.get("bbox"), "confidence": p.get("confidence", 0.9)}
                for i, p in enumerate(tracking_payload)
            ]

    # --- Step 3: Determine PPE status per person ---
    # Collect all non-person YOLO classes (PPE detections) globally for this frame.
    # A production system would spatially assign PPE to each person bbox (IoU overlap).
    # For now, missing PPE flags apply to all detected persons in the frame.
    all_classes = {
        str(d.get("class_name") or d.get("class") or d.get("label", "")).lower()
        for d in raw_detections
        if isinstance(d, dict)
    }

    workers: list[DetectedWorker] = []
    for idx, track in enumerate(tracks):
        worker_id = _worker_id_from_track(track.get("track_id"), idx)
        missing = _missing_ppe_from_classes(all_classes)
        workers.append(DetectedWorker(
            worker_id=worker_id,
            zone_id=req.zone_id,
            present=True,
            missing_ppe=missing,
            confidence=float(track.get("confidence", vision_resp.confidence or 0.9)),
            bbox=track.get("bbox"),
        ))

    log.info(
        "vision.detect: zone=%s detected=%d workers from %d raw detections",
        req.zone_id, len(workers), len(raw_detections),
    )
    return VisionDetectResponse(
        zone_id=req.zone_id,
        detected_workers=workers,
        inference_mode="real",
        model_name=vision_resp.model_name,
        model_version=vision_resp.model_version,
    )

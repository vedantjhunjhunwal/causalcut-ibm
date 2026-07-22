"""Model-backed canonical event generation.

This is the bridge required by the architecture:

    scenario raw features -> shared inference service -> REAL model prediction
    -> Canonical Event Schema -> event queue -> hypergraph -> ...

Nothing here invents a prediction. If a model is unavailable the reading is
skipped and a structured degradation record is returned, so the scenario result
and the dashboard can state exactly which models ran, which did not, and why.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from app.schemas.canonical import SafetyEvent
from app.schemas.enums import InformationClass
from app.schemas.scenario import Scenario
from app.services.model_service import (
    InvalidFeaturesError,
    ModelResponse,
    get_registry,
)

log = logging.getLogger("causalcut.model_events")


def _record(resp: ModelResponse, called: str, ok: bool, note: str = "") -> dict[str, Any]:
    return {
        "model_name": resp.model_name,
        "model_version": resp.model_version,
        "called": called,
        "ran": ok,
        "inference_mode": resp.inference_mode,
        "confidence": resp.confidence,
        "latency_ms": resp.latency_ms,
        "artifact_path": resp.artifact_path,
        "degraded_reason": resp.degraded_reason or (note or None),
        "correlation_id": resp.correlation_id,
        "scenario_id": resp.scenario_id,
        "timestamp": resp.timestamp,
    }


def generate_model_events(
    scenario: Scenario, correlation_id: str
) -> tuple[list[SafetyEvent], list[dict[str, Any]]]:
    """Run every applicable trained model and lower predictions to canonical events.

    Returns ``(events, provenance_records)``.
    """
    registry = get_registry()
    anchor = scenario.effective_base_time
    events: list[SafetyEvent] = []
    provenance: list[dict[str, Any]] = []

    # ---------------------------------------------------------------- gas ---
    # Disabled per user request
    pass

    # ------------------------------------------------------------ machine ---
    for m in scenario.machine_readings:
        feats = m.model_dump(exclude={"asset_id", "zone_id", "offset_seconds"})
        resp = registry.machine.predict(
            feats, correlation_id=correlation_id, scenario_id=scenario.scenario_id)
        provenance.append(_record(resp, f"machine:{m.asset_id}", resp.inference_mode == "real"))
        if resp.inference_mode != "real":
            continue
        probs: dict[str, float] = (resp.prediction or {}).get("probabilities", {})
        mode_probs = {k: v for k, v in probs.items() if k != "Machine_failure"}
        worst_mode = (resp.prediction or {}).get("top_failure_mode") or (
            max(mode_probs, key=mode_probs.get) if mode_probs else "unknown")
        # Overall machine-failure probability drives severity; fall back to the
        # dominant mode if the combined target is absent.
        worst_p = float((resp.prediction or {}).get("machine_failure")
                        or (mode_probs.get(worst_mode, 0.0) if mode_probs else 0.0))
        failure_modes = (resp.prediction or {}).get("failure_modes", [])
        events.append(SafetyEvent(
            factory_id=scenario.factory_id,
            zone_id=m.zone_id,
            asset_id=m.asset_id,
            event_type="equipment_failure",
            event_time=anchor + timedelta(seconds=m.offset_seconds),
            value={
                "failure_probability": worst_p,
                "failure_mode": worst_mode,
                "failure_modes": failure_modes,
                "mode_probabilities": probs,
                "model_name": resp.model_name,
                "inference_mode": resp.inference_mode,
                "correlation_id": correlation_id,
                "scenario_id": scenario.scenario_id,
            },
            severity=min(1.0, worst_p),
            confidence=resp.confidence or 0.0,
            source=resp.model_name,
            model_version=resp.model_version,
            provenance=resp.artifact_path,
            information_class=InformationClass.PREDICTED,
        ))

    # ---------------------------------------------------------- hydraulic ---
    for h in scenario.hydraulic_readings:
        if not h.sensor_data:
            continue
        try:
            resp = registry.hydraulic.predict(
                h.sensor_data, correlation_id=correlation_id, scenario_id=scenario.scenario_id)
        except InvalidFeaturesError as exc:
            provenance.append({
                "model_name": "hydraulic_lgbm_multioutput", "called": f"hydraulic:{h.zone_id}",
                "ran": False, "inference_mode": "error", "degraded_reason": str(exc),
                "correlation_id": correlation_id, "scenario_id": scenario.scenario_id,
            })
            continue
        provenance.append(_record(resp, f"hydraulic:{h.zone_id}", resp.inference_mode == "real"))
        if resp.inference_mode != "real":
            continue
        preds: dict[str, Any] = resp.prediction or {}
        # Cooler_Condition: 3 = near total failure, 100 = full efficiency.
        cooler = float(preds.get("Cooler_Condition", 100))
        flow_ratio = max(0.0, min(1.0, cooler / 100.0))
        events.append(SafetyEvent(
            factory_id=scenario.factory_id,
            zone_id=h.zone_id,
            event_type="utility_condition",
            event_time=anchor + timedelta(seconds=h.offset_seconds),
            value={
                "ventilation_flow_ratio": round(flow_ratio, 3),
                "hydraulic_conditions": preds,
                "model_name": resp.model_name,
                "inference_mode": resp.inference_mode,
                "correlation_id": correlation_id,
                "scenario_id": scenario.scenario_id,
            },
            severity=round(1.0 - flow_ratio, 3),
            confidence=0.8,
            source=resp.model_name,
            model_version=resp.model_version,
            provenance=resp.artifact_path,
            information_class=InformationClass.PREDICTED,
        ))

    # ------------------------------------------------------------- vision ---
    for v in scenario.vision_inputs:
        image_ref = ({"format": "base64", "data": v.image_b64}
                     if v.image_b64 else v.image_ref)
        try:
            resp = registry.vision.detect(image_ref, correlation_id=correlation_id,
                                          scenario_id=scenario.scenario_id)
        except Exception as exc:
            # An unreadable frame is bad operator input, not a pipeline fault:
            # record the degradation and carry on with the remaining evidence
            # rather than aborting the whole scenario.
            log.warning("vision inference failed for %s: %s", v.image_id, exc)
            provenance.append({
                "model_name": "vision_yolov8", "called": f"vision:{v.image_id}",
                "ran": False, "inference_mode": "error", "degraded_reason": str(exc),
                "correlation_id": correlation_id, "scenario_id": scenario.scenario_id,
            })
            continue
        provenance.append(_record(resp, f"vision:{v.image_id}",
                                  resp.inference_mode == "real"))
        if resp.inference_mode != "real":
            # Unavailable checkpoint/dependency: report, never fabricate a
            # PPE detection. The rest of the pipeline continues on real data.
            continue

        detections = resp.prediction or []
        if hasattr(detections, "to_dict"):
            detections = detections.to_dict()
        if isinstance(detections, dict):
            detections = detections.get("detections", [])
        # PPE classes the model reports as ABSENT constitute a violation.
        classes = {str(d.get("class") or d.get("label", "")).lower()
                   for d in detections if isinstance(d, dict)}
        missing = [ppe for ppe in ("hard_hat", "helmet", "vest")
                   if ppe not in classes and "person" in classes]
        if missing:
            events.append(SafetyEvent(
                factory_id=scenario.factory_id,
                zone_id=v.zone_id,
                worker_id=v.worker_id,
                event_type="ppe_violation",
                event_time=anchor + timedelta(seconds=v.offset_seconds),
                value={
                    "missing_ppe": missing,
                    "detections": detections,
                    "image_id": v.image_id,
                    "frame_id": v.frame_id,
                    "model_name": resp.model_name,
                    "model_version": resp.model_version,
                    "confidence": resp.confidence,
                    "inference_mode": resp.inference_mode,
                    "latency_ms": resp.latency_ms,
                    "degraded_reason": resp.degraded_reason,
                    "correlation_id": correlation_id,
                    "scenario_id": scenario.scenario_id,
                },
                severity=0.5,
                confidence=resp.confidence or 0.0,
                source=resp.model_name,
                model_version=resp.model_version,
                provenance=resp.artifact_path,
                information_class=InformationClass.PREDICTED,
            ))

    # ----------------------------------------------------------- tracking ---
    for t in scenario.tracking_inputs:
        if not t.detections:
            continue
        payload = [{"frame_id": d.frame_id, "bbox": d.bbox,
                    "class": d.object_class, "confidence": d.confidence}
                   for d in t.detections]
        try:
            resp = registry.tracking.update(payload, correlation_id=correlation_id,
                                            scenario_id=scenario.scenario_id)
        except Exception as exc:
            log.warning("tracking inference failed for %s: %s", t.zone_id, exc)
            provenance.append({
                "model_name": "tracking_bytetrack", "called": f"tracking:{t.zone_id}",
                "ran": False, "inference_mode": "error", "degraded_reason": str(exc),
                "correlation_id": correlation_id, "scenario_id": scenario.scenario_id,
            })
            continue
        provenance.append(_record(resp, f"tracking:{t.zone_id}",
                                  resp.inference_mode == "real"))
        if resp.inference_mode != "real":
            continue  # no fabricated tracks

        tracks = resp.prediction or []
        if isinstance(tracks, dict):
            tracks = tracks.get("tracks", [])
        for tr in tracks:
            if not isinstance(tr, dict):
                continue
            events.append(SafetyEvent(
                factory_id=scenario.factory_id,
                zone_id=t.zone_id,
                worker_id=tr.get("worker_id") or f"T-{tr.get('track_id', 0)}",
                event_type="worker_presence",
                event_time=anchor + timedelta(seconds=t.offset_seconds),
                value={
                    "present": True,
                    "track_id": tr.get("track_id"),
                    "bbox": tr.get("bbox"),
                    "model_name": resp.model_name,
                    "model_version": resp.model_version,
                    "inference_mode": resp.inference_mode,
                    "latency_ms": resp.latency_ms,
                    "degraded_reason": resp.degraded_reason,
                    "correlation_id": correlation_id,
                    "scenario_id": scenario.scenario_id,
                },
                severity=0.0,
                confidence=float(tr.get("confidence", resp.confidence or 0.0)),
                source=resp.model_name,
                model_version=resp.model_version,
                provenance=resp.artifact_path,
                information_class=InformationClass.PREDICTED,
            ))

    events.sort(key=lambda e: e.event_time)
    return events, provenance

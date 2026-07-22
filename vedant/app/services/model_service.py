"""Shared model inference service layer.

ONE place that loads each trained artifact (once), applies the *real*
preprocessing the model was trained with, runs real inference, and returns a
stable JSON-serialisable response. Both the ``/api/v1/models/*`` routes and the
scenario orchestrator call these services — model logic is never duplicated in
a route.

Non-negotiable rule: services NEVER fabricate predictions. If an artifact,
checkpoint, dependency or preprocessing object is missing, the service reports
``inference_mode="degraded"`` (or ``"unavailable"``) with a ``degraded_reason``
and returns no invented numbers. ``mock`` mode exists only for tests and is
never selected implicitly.

Reality in this build (see INTEGRATION_REPORT):
  * gas (XGBoost + IsolationForest)  -> REAL (artifacts present, CPU inference)
  * hydraulic (LightGBM multi-output) -> REAL (artifacts present, CPU inference)
  * machine-failure (AI4I LightGBM)   -> UNAVAILABLE (artifact not in repo)
  * vision (YOLOv8) / tracking (ByteTrack) -> UNAVAILABLE without torch
  * regulatory (FAISS RAG)            -> REAL if faiss+embeddings present, else DEGRADED
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("causalcut.models")

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ModelUnavailableError(RuntimeError):
    """Raised when a caller demands real inference from an unavailable model."""


class InvalidFeaturesError(ValueError):
    """Raised when the supplied features do not match the model's contract."""


@dataclass
class ModelResponse:
    """Stable, JSON-serialisable inference envelope (never exposes raw arrays)."""

    model_name: str
    model_version: str
    prediction: Any
    confidence: Optional[float]
    inference_mode: str                      # real | degraded | unavailable | mock
    latency_ms: float
    correlation_id: str
    scenario_id: Optional[str] = None
    artifact_path: Optional[str] = None
    degraded_reason: Optional[str] = None
    timestamp: str = field(default_factory=_utcnow_iso)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.update(d.pop("extra"))
        return d


class BaseModelService:
    name = "base"
    version = "0.0.0"
    # Dependencies that must import for this model to serve real inference.
    required_deps: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._loaded = False
        self._load_error: str | None = None
        self._ready: bool | None = None
        self._ready_error: str | None = None

    # Each subclass implements _load() (idempotent) and sets self._loaded.
    def _load(self) -> None:  # pragma: no cover - overridden
        self._loaded = True

    def ensure_loaded(self) -> None:
        if self._loaded or self._load_error is not None:
            return
        try:
            self._load()
            self._loaded = True
        except Exception as exc:  # keep the service alive; report degraded.
            self._load_error = str(exc)
            log.warning("model '%s' failed to load: %s", self.name, exc)

    @property
    def available(self) -> bool:
        self.ensure_loaded()
        return self._loaded and self._load_error is None

    @property
    def artifact_path(self) -> str | None:
        return None

    # -- readiness probing ------------------------------------------------ #
    def artifact_found(self) -> bool:
        """Does the artifact actually exist on disk?"""
        p = self.artifact_path
        if p is None:
            return False
        return Path(p).exists()

    def dependency_status(self) -> dict[str, str]:
        """Import-check every required dependency: 'ok' or the import error."""
        out: dict[str, str] = {}
        import importlib
        for dep in self.required_deps:
            try:
                importlib.import_module(dep)
                out[dep] = "ok"
            except Exception as exc:
                out[dep] = f"missing: {type(exc).__name__}: {exc}"
        return out

    def _smoke_check(self) -> None:
        """Lightweight inference/initialisation check. Override per model.

        Must raise if the model cannot actually serve a request.
        """
        return

    def readiness(self) -> tuple[bool, str | None]:
        """True only when artifact + deps + load + smoke check all pass."""
        if self._ready is not None:
            return self._ready, self._ready_error

        deps = self.dependency_status()
        bad = [f"{k} ({v})" for k, v in deps.items() if v != "ok"]
        if bad:
            self._ready, self._ready_error = False, "dependency unavailable: " + "; ".join(bad)
            return self._ready, self._ready_error

        if self.artifact_path is not None and not self.artifact_found():
            self._ready, self._ready_error = False, f"artifact not found: {self.artifact_path}"
            return self._ready, self._ready_error

        self.ensure_loaded()
        if not self.available:
            self._ready, self._ready_error = False, f"load failed: {self._load_error}"
            return self._ready, self._ready_error

        try:
            self._smoke_check()
        except Exception as exc:
            self._ready, self._ready_error = False, f"inference check failed: {exc}"
            return self._ready, self._ready_error

        self._ready, self._ready_error = True, None
        return self._ready, self._ready_error

    def status(self) -> dict[str, Any]:
        ready, reason = self.readiness()
        deps = self.dependency_status()
        return {
            "model_name": self.name,
            "model_version": self.version if ready else str(self.version),
            "available": ready,
            "ready": ready,
            "artifact_found": self.artifact_found() if self.artifact_path else None,
            "artifact_path": self.artifact_path,
            "dependency_status": deps,
            "inference_mode": "real" if ready else "unavailable",
            "degraded_reason": reason,
        }


# --------------------------------------------------------------------------- #
# Gas — XGBoost classifier + IsolationForest drift (REAL)
# --------------------------------------------------------------------------- #
class GasModelService(BaseModelService):
    name = "gas_xgboost_isoforest"
    required_deps = ("numpy", "joblib", "sklearn", "xgboost")

    def _smoke_check(self) -> None:
        import numpy as np
        self._pipeline.infer(np.zeros(128), sensor_id="GS-01", zone_id="zone-1")

    def __init__(self, xgb_path: str | None = None, iso_path: str | None = None) -> None:
        super().__init__()
        self._xgb_path = xgb_path
        self._iso_path = iso_path
        self._pipeline = None

    def _load(self) -> None:
        import sys
        src = str(_REPO_ROOT / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        from inference.gas_inference import GasInferencePipeline  # real module
        self._pipeline = GasInferencePipeline(
            xgb_model_path=self._xgb_path, isoforest_model_path=self._iso_path
        )
        self._pipeline._load_models()  # force artifact load now (fail fast)

    @property
    def version(self) -> str:  # type: ignore[override]
        return self._pipeline.model_version if self._pipeline else "xgb-gas-unloaded"

    @property
    def artifact_path(self) -> str | None:
        return self._pipeline.xgb_path if self._pipeline else self._xgb_path

    def predict(
        self,
        features: list[float],
        sensor_id: str = "GS-03",
        zone_id: str = "zone-1",
        correlation_id: str | None = None,
        scenario_id: str | None = None,
        require_real: bool = False,
    ) -> ModelResponse:
        cid = correlation_id or str(uuid.uuid4())
        t0 = time.perf_counter()
        ready, ready_reason = self.readiness()
        if not ready:
            if require_real:
                raise ModelUnavailableError(f"gas model unavailable: {ready_reason}")
            return ModelResponse(
                model_name=self.name, model_version="unavailable", prediction=None,
                confidence=None, inference_mode="degraded", latency_ms=0.0,
                correlation_id=cid, scenario_id=scenario_id,
                degraded_reason=f"gas model not ready: {ready_reason}",
            )
        if features is None or len(features) != 128:
            raise InvalidFeaturesError(
                f"gas model expects a 128-dim feature vector (16 sensors x 8 features), "
                f"got {0 if features is None else len(features)}"
            )
        event = self._pipeline.infer(features, sensor_id=sensor_id, zone_id=zone_id)
        latency = round((time.perf_counter() - t0) * 1000, 3)
        log.info("gas inference", extra={"correlation_id": cid, "scenario_id": scenario_id,
                                          "sensor": sensor_id, "gas": event["value"]["gas_type"],
                                          "confidence": event["confidence"]})
        return ModelResponse(
            model_name=self.name, model_version=self.version,
            prediction={"event_type": event["event_type"],
                        "gas_type": event["value"]["gas_type"],
                        "concentration_ppm": event["value"]["concentration_ppm"],
                        "drift_detected": event["value"]["drift_detected"],
                        "anomaly_score": event["value"]["anomaly_score"],
                        "gas_class_probabilities": event["value"]["gas_class_probabilities"]},
            confidence=event["confidence"], inference_mode="real", latency_ms=latency,
            correlation_id=cid, scenario_id=scenario_id, artifact_path=self.artifact_path,
            extra={"severity": event["severity"], "canonical_event": event},
        )


# --------------------------------------------------------------------------- #
# Hydraulic — LightGBM multi-output (REAL)
# --------------------------------------------------------------------------- #
_HYD_SENSORS = ["PS1", "PS2", "PS3", "PS4", "PS5", "PS6", "EPS1", "FS1", "FS2",
                "TS1", "TS2", "TS3", "TS4", "VS1", "CE", "CP", "SE"]


class HydraulicModelService(BaseModelService):
    name = "hydraulic_lgbm_multioutput"
    version = "lgbm-hydraulic-1.0"
    required_deps = ("numpy", "pandas", "joblib", "sklearn", "lightgbm", "scipy")

    def _smoke_check(self) -> None:
        probe = {s_: [0.0] * 10 for s_ in _HYD_SENSORS}
        feats = self._infer.extract_features_for_cycle(probe)
        self._infer.predict(self._pipelines, self._encoders, feats)

    def __init__(self, model_dir: str | None = None) -> None:
        super().__init__()
        self._dir = model_dir or str(_REPO_ROOT / ".models" / "Hydraulic Classifier")
        self._pipelines = None
        self._encoders = None
        self._infer = None

    def _load(self) -> None:
        import importlib.util
        inf_path = Path(self._dir) / "inference.py"
        spec = importlib.util.spec_from_file_location("hyd_inference", inf_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        self._infer = mod
        self._pipelines, self._encoders = mod.load_artifacts(self._dir, self.version)

    @property
    def artifact_path(self) -> str | None:
        return str(Path(self._dir) / f"{self.version}_pipelines.joblib")

    def predict(
        self,
        sensor_data: dict[str, list[float]],
        correlation_id: str | None = None,
        scenario_id: str | None = None,
        require_real: bool = False,
    ) -> ModelResponse:
        cid = correlation_id or str(uuid.uuid4())
        t0 = time.perf_counter()
        ready, ready_reason = self.readiness()
        if not ready:
            if require_real:
                raise ModelUnavailableError(f"hydraulic model unavailable: {ready_reason}")
            return ModelResponse(self.name, "unavailable", None, None, "degraded", 0.0,
                                 cid, scenario_id, degraded_reason=f"hydraulic model not ready: {ready_reason}")
        missing = [s for s in _HYD_SENSORS if s not in sensor_data]
        if missing:
            raise InvalidFeaturesError(f"hydraulic model missing sensor cycles: {missing}")
        feats = self._infer.extract_features_for_cycle(sensor_data)
        preds = self._infer.predict(self._pipelines, self._encoders, feats)
        # Never expose raw numpy scalars (requirement: JSON-serialisable only).
        preds = {k: (int(v) if hasattr(v, "__int__") and not isinstance(v, bool) else
                     (v.item() if hasattr(v, "item") else v)) for k, v in preds.items()}
        latency = round((time.perf_counter() - t0) * 1000, 3)
        log.info("hydraulic inference", extra={"correlation_id": cid, "scenario_id": scenario_id,
                                                "preds": preds})
        return ModelResponse(self.name, self.version, preds, None, "real", latency,
                             cid, scenario_id, artifact_path=self.artifact_path)


# --------------------------------------------------------------------------- #
# Machine failure — AI4I LightGBM (artifact NOT in repo -> UNAVAILABLE)
# --------------------------------------------------------------------------- #
class MachineFailureModelService(BaseModelService):
    name = "machine_failure_ai4i_lgbm"
    version = "lgbm-ai4i-1.0"
    required_deps = ("numpy", "pandas", "joblib", "sklearn", "lightgbm")

    def _smoke_check(self) -> None:
        import pandas as pd
        probe = {"Type": "M", "Air_temperature": 298.1, "Process_temperature": 308.6,
                 "Rotational_speed": 1500, "Torque": 40.0, "Tool_wear": 0}
        df = pd.DataFrame([{k: probe[k] for k in self._feature_order}],
                          columns=self._feature_order)
        self._load_mod.predict_probabilities(self._pipelines, df)

    # Fallback only; the authoritative order is read from the artifact itself
    # (``feature_names_in_``) so preprocessing matches training exactly.
    _FALLBACK_FEATURES = ["Type", "Air_temperature", "Process_temperature",
                          "Rotational_speed", "Torque", "Tool_wear"]

    def __init__(self, model_dir: str | None = None) -> None:
        super().__init__()
        self._dir = model_dir or str(_REPO_ROOT / ".models" / "AI4I Classifier")
        self._pipelines = None
        self._load_mod = None
        self._feature_order: list[str] = list(self._FALLBACK_FEATURES)
        self._targets: list[str] = []

    def _load(self) -> None:
        import importlib.util
        inf_path = Path(self._dir) / "inference.py"
        spec = importlib.util.spec_from_file_location("ai4i_inference", inf_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        self._load_mod = mod
        # Team's own loader — one loader, no duplicate implementation.
        self._pipelines = mod.load_artifacts(self._dir, self.version)  # raises if missing
        self._targets = list(self._pipelines.keys())

        # Recover the EXACT training feature order from the fitted preprocessor
        # rather than trusting a hardcoded list.
        try:
            any_target = next(iter(self._pipelines.values()))
            est = any_target.calibrated_classifiers_[0].estimator
            pre = est.named_steps["preprocessor"]
            names = list(getattr(pre, "feature_names_in_", []))
            if names:
                self._feature_order = names
        except Exception as exc:  # pragma: no cover - artifact shape variance
            log.warning("could not read feature order from AI4I artifact (%s); "
                        "using documented fallback order", exc)

    @property
    def artifact_path(self) -> str | None:
        return str(Path(self._dir) / f"{self.version}_pipelines.joblib")

    @property
    def feature_order(self) -> list[str]:
        self.ensure_loaded()
        return list(self._feature_order)

    def status(self) -> dict[str, Any]:
        st = super().status()
        st["feature_order"] = self.feature_order
        st["failure_modes"] = list(self._targets)
        return st

    def predict(
        self,
        features: dict[str, Any],
        correlation_id: str | None = None,
        scenario_id: str | None = None,
        require_real: bool = False,
    ) -> ModelResponse:
        cid = correlation_id or str(uuid.uuid4())
        t0 = time.perf_counter()
        ready, ready_reason = self.readiness()
        if not ready:
            if require_real:
                raise ModelUnavailableError(f"machine-failure model unavailable: {ready_reason}")
            return ModelResponse(self.name, "unavailable", None, None, "degraded", 0.0,
                                 cid, scenario_id, artifact_path=self.artifact_path,
                                 degraded_reason=f"machine model not ready: {ready_reason}",
                                 extra={"failure_modes": [], "probabilities": {}})
        import pandas as pd

        order = self._feature_order
        missing = [k for k in order if k not in features]
        if missing:
            raise InvalidFeaturesError(
                f"machine model missing features: {missing}; required order: {order}")
        # Build the frame in the trained column order; the pipeline's
        # MinMaxScaler + OneHotEncoder then apply the training preprocessing.
        df = pd.DataFrame([{k: features[k] for k in order}], columns=order)
        probs = self._load_mod.predict_probabilities(self._pipelines, df)
        # Native JSON types only — never numpy scalars.
        probs = {k: round(float(v), 6) for k, v in probs.items()}

        mode_probs = {k: v for k, v in probs.items() if k != "Machine_failure"}
        overall = probs.get("Machine_failure")
        top_mode = max(mode_probs, key=mode_probs.get) if mode_probs else None
        threshold = get_settings_confidence()
        failure_modes = sorted(
            [m for m, p in mode_probs.items() if p >= threshold],
            key=lambda m: mode_probs[m], reverse=True,
        )
        confidence = float(max(probs.values())) if probs else None
        latency = round((time.perf_counter() - t0) * 1000, 3)

        log.info("machine-failure inference",
                 extra={"correlation_id": cid, "scenario_id": scenario_id,
                        "top_mode": top_mode, "machine_failure_p": overall,
                        "failure_modes": failure_modes})

        return ModelResponse(
            model_name=self.name, model_version=self.version,
            prediction={
                "machine_failure": overall,
                "top_failure_mode": top_mode,
                "failure_modes": failure_modes,
                "probabilities": probs,
            },
            confidence=confidence, inference_mode="real", latency_ms=latency,
            correlation_id=cid, scenario_id=scenario_id, artifact_path=self.artifact_path,
            extra={
                "failure_modes": failure_modes,
                "probabilities": probs,
                "feature_order": order,
                "decision_threshold": threshold,
            },
        )


def get_settings_confidence() -> float:
    """Confidence threshold used to call a failure mode 'active'."""
    try:
        from app.core.config import get_settings
        return float(get_settings().model_confidence_threshold)
    except Exception:  # pragma: no cover
        return 0.5


# --------------------------------------------------------------------------- #
# Vision (YOLOv8) + Tracking (ByteTrack) — need torch (UNAVAILABLE here)
# --------------------------------------------------------------------------- #
class VisionModelService(BaseModelService):
    name = "vision_yolov8_ppe"
    version = "yolov8n-ppe-1.0"
    required_deps = ("torch", "ultralytics")

    def _smoke_check(self) -> None:
        if self._detector is None:
            raise RuntimeError("detector not initialised")

    def __init__(self, model_path: str | None = None) -> None:
        super().__init__()
        self._path = model_path or str(_REPO_ROOT / "models" / "yolov8_ppe.pt")
        self._detector = None

    def _load(self) -> None:
        import torch  # noqa: F401  (raises ImportError here -> degraded)
        import sys
        src = str(_REPO_ROOT / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        from inference.yolo_detector import YOLODetector  # type: ignore
        self._detector = YOLODetector(model_path=self._path)

    @property
    def artifact_path(self) -> str | None:
        return self._path

    def detect(self, image_ref: Any, correlation_id: str | None = None,
               scenario_id: str | None = None, require_real: bool = False) -> ModelResponse:
        cid = correlation_id or str(uuid.uuid4())
        ready, ready_reason = self.readiness()
        if not ready:
            if require_real:
                raise ModelUnavailableError(f"vision model unavailable: {ready_reason}")
            return ModelResponse(self.name, "unavailable", None, None, "degraded", 0.0,
                                 cid, scenario_id,
                                 degraded_reason=f"vision model not ready: {ready_reason}")
        t0 = time.perf_counter()
        detections = self._detector.detect(image_ref)
        latency = round((time.perf_counter() - t0) * 1000, 3)
        return ModelResponse(self.name, self.version, detections, None, "real", latency,
                             cid, scenario_id, artifact_path=self.artifact_path)


class TrackingModelService(BaseModelService):
    name = "tracking_bytetrack"
    version = "bytetrack-1.0"
    # ByteTrack re-identification needs the tracking stack; without it the
    # service must NOT report ready (it previously did, which was a false
    # positive because it had no artifact and no dependency check).
    required_deps = ("numpy", "supervision")

    _tracker = None

    def _smoke_check(self) -> None:
        if self._tracker is None:
            raise RuntimeError("tracker not initialised")

    def _load(self) -> None:
        import sys
        src = str(_REPO_ROOT / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        from inference.vision_tracker import VisionTracker  # type: ignore
        self._tracker = VisionTracker()

    def update(self, detections: list[dict], correlation_id: str | None = None,
               scenario_id: str | None = None, require_real: bool = False) -> ModelResponse:
        cid = correlation_id or str(uuid.uuid4())
        ready, ready_reason = self.readiness()
        if not ready:
            if require_real:
                raise ModelUnavailableError(f"tracking model unavailable: {ready_reason}")
            return ModelResponse(self.name, "unavailable", None, None, "degraded", 0.0,
                                 cid, scenario_id,
                                 degraded_reason=f"tracking model not ready: {ready_reason}")
        t0 = time.perf_counter()
        tracks = self._tracker.update(detections)
        latency = round((time.perf_counter() - t0) * 1000, 3)
        return ModelResponse(self.name, self.version, tracks, None, "real", latency,
                             cid, scenario_id)


# --------------------------------------------------------------------------- #
# Regulatory — FAISS RAG verifier (REAL if deps present, else DEGRADED)
# --------------------------------------------------------------------------- #
_STATIC_CLAUSES = [
    ("suspend", "hot", "OISD-STD-116 Clause 4.3",
     "Hot work shall be stopped immediately when a hazardous atmosphere is detected."),
    ("permit", "", "OISD-STD-105",
     "Work permits must be revalidated when zone conditions change materially."),
    ("evacuate", "", "Factories Act 1948, Section 41",
     "No worker shall be required to work in conditions injurious to health."),
    ("ventilation", "", "OISD-STD-118",
     "Mechanical ventilation must be maintained in confined/toxic areas."),
    ("isolat", "", "OISD-STD-116 Clause 5.1",
     "Isolation of hazardous energy/gas sources is required before intervention."),
    ("close", "", "Factories Act 1948, Section 87",
     "Dangerous operations may be restricted to protect worker safety."),
]


class RegulatoryModelService(BaseModelService):
    """FAISS semantic RAG, degrading to lexical retrieval over the SAME corpus.

    Three tiers, all drawing on real regulatory documents:
      * ``real``     — FAISS + sentence-transformers semantic retrieval.
      * ``degraded`` — BM25-style lexical retrieval over the real chunk corpus
                       (`regulatory_metadata.json`, 241 OISD/Factories Act
                       chunks). Citations are genuine document clauses; only
                       the *ranking* is lexical rather than semantic.
      * unavailable  — corpus missing entirely; returns no citations.

    No tier invents a clause that is not in the corpus.
    """

    name = "regulatory_faiss_rag"
    version = "faiss-rag-1.0"
    required_deps = ("faiss", "sentence_transformers")

    def _smoke_check(self) -> None:
        if self._verifier is None:
            raise RuntimeError("verifier not initialised")

    def __init__(self) -> None:
        super().__init__()
        self._verifier = None
        self._corpus: list[dict] | None = None

    def _load(self) -> None:
        import sys
        rag_dir = str(_REPO_ROOT / "regulatory_rag")
        if rag_dir not in sys.path:
            sys.path.insert(0, rag_dir)
        from regulatory_rag.verifier import ComplianceVerifier  # type: ignore
        import faiss  # noqa: F401
        self._verifier = ComplianceVerifier()

    @property
    def artifact_path(self) -> str | None:
        return str(_REPO_ROOT / "regulatory_rag" / "faiss_store" / "regulatory.index")

    @property
    def corpus_path(self) -> Path:
        return _REPO_ROOT / "regulatory_rag" / "faiss_store" / "regulatory_metadata.json"

    def _load_corpus(self) -> list[dict]:
        if self._corpus is None:
            try:
                import json as _json
                self._corpus = _json.loads(self.corpus_path.read_text())
            except Exception as exc:
                log.warning("regulatory corpus unavailable: %s", exc)
                self._corpus = []
        return self._corpus

    @staticmethod
    def _tokens(text: str) -> list[str]:
        import re
        return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2]

    def _lexical_search(self, query: str, k: int = 2) -> list[dict]:
        """Rank real corpus chunks by term overlap (idf-weighted)."""
        import math
        corpus = self._load_corpus()
        if not corpus:
            return []
        q = set(self._tokens(query))
        if not q:
            return []
        n = len(corpus)
        # Document frequency for the query terms only (cheap).
        df = {t: 0 for t in q}
        toks_cache = []
        for c in corpus:
            ts = set(self._tokens(c.get("text", "")))
            toks_cache.append(ts)
            for t in q:
                if t in ts:
                    df[t] += 1
        scored = []
        for c, ts in zip(corpus, toks_cache):
            score = sum(math.log(1 + n / (1 + df[t])) for t in q if t in ts)
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:k]]

    def verify(self, actions: list[str], zone_context: str = "",
               correlation_id: str | None = None, scenario_id: str | None = None) -> ModelResponse:
        cid = correlation_id or str(uuid.uuid4())
        t0 = time.perf_counter()
        citations: list[dict[str, Any]] = []
        ready, ready_reason = self.readiness()

        if ready:
            try:
                for action in actions:
                    res = self._verifier.verify_action(action, zone_context)
                    if res.get("verified"):
                        for ev in res.get("evidence", [])[:2]:
                            citations.append({
                                "action": action,
                                "clause": ev.get("source") or ev.get("citation") or "regulatory",
                                "text": (ev.get("text") or "")[:400],
                                "retrieval": "semantic_faiss",
                                "info_class": "R"})
                if citations:
                    latency = round((time.perf_counter() - t0) * 1000, 3)
                    return ModelResponse(self.name, self.version, {"citations": citations},
                                         None, "real", latency, cid, scenario_id,
                                         artifact_path=self.artifact_path)
            except Exception as exc:
                ready_reason = str(exc)

        # Degraded tier: lexical retrieval over the REAL corpus.
        corpus = self._load_corpus()
        for action in actions:
            for chunk in self._lexical_search(f"{action} {zone_context}", k=1):
                citations.append({
                    "action": action,
                    "clause": chunk.get("citation") or chunk.get("doc_id", "regulatory"),
                    "text": (chunk.get("text") or "")[:400],
                    "document": chunk.get("title"),
                    "chunk_id": chunk.get("chunk_id"),
                    "retrieval": "lexical_bm25",
                    "info_class": "R",
                })
        latency = round((time.perf_counter() - t0) * 1000, 3)
        reason = (f"FAISS semantic retrieval unavailable ({ready_reason}); "
                  f"used lexical retrieval over the real {len(corpus)}-chunk corpus")
        if not corpus:
            reason = f"regulatory corpus unavailable: {ready_reason}"
        return ModelResponse(self.name, "lexical-retrieval-1.0", {"citations": citations},
                             None, "degraded", latency, cid, scenario_id,
                             degraded_reason=reason, artifact_path=self.artifact_path)


# --------------------------------------------------------------------------- #
# Registry (singletons; shared by routes + orchestrator)
# --------------------------------------------------------------------------- #
class ModelRegistry:
    """Holds one service per model.

    If a ``*_MODEL_API_URL`` is configured the corresponding service is a
    ``RemoteModelService`` (HTTP call to a separate model server); otherwise it
    is the in-process service that loads the artifact locally. Callers use an
    identical interface either way, so the scenario pipeline is unaffected.
    """

    def __init__(self) -> None:
        from app.core.config import get_settings
        s = get_settings()
        self.settings = s

        rk = dict(timeout_s=s.model_request_timeout_s,
                  retries=s.model_retry_count,
                  backoff_s=s.model_retry_backoff_s)

        if s.gas_model_api_url:
            from app.services.remote_model_client import RemoteGasService
            self.gas = RemoteGasService("gas_xgboost_isoforest", s.gas_model_api_url, **rk)
        else:
            self.gas = GasModelService(s.gas_xgb_model_path, s.gas_isoforest_model_path)

        if s.hydraulic_model_api_url:
            from app.services.remote_model_client import RemoteHydraulicService
            self.hydraulic = RemoteHydraulicService(
                "hydraulic_lgbm_multioutput", s.hydraulic_model_api_url, **rk)
        else:
            self.hydraulic = HydraulicModelService(s.hydraulic_model_dir)

        if s.machine_model_api_url:
            from app.services.remote_model_client import RemoteMachineService
            self.machine = RemoteMachineService(
                "machine_failure_ai4i_lgbm", s.machine_model_api_url, **rk)
        else:
            self.machine = MachineFailureModelService(s.machine_model_dir)

        if s.vision_model_api_url:
            from app.services.remote_model_client import RemoteVisionService
            self.vision = RemoteVisionService("vision_yolov8_ppe", s.vision_model_api_url, **rk)
        else:
            self.vision = VisionModelService(s.vision_model_path)

        if s.tracking_model_api_url:
            from app.services.remote_model_client import RemoteTrackingService
            self.tracking = RemoteTrackingService(
                "tracking_bytetrack", s.tracking_model_api_url, **rk)
        else:
            self.tracking = TrackingModelService()

        if s.rag_model_api_url:
            from app.services.remote_model_client import RemoteRegulatoryService
            self.regulatory = RemoteRegulatoryService(
                "regulatory_faiss_rag", s.rag_model_api_url, **rk)
        else:
            self.regulatory = RegulatoryModelService()

    def transport(self, key: str) -> str:
        svc = self.all().get(key)
        return "remote" if svc.__class__.__module__.endswith("remote_model_client") else "in_process"

    def all(self) -> dict[str, BaseModelService]:
        return {"gas": self.gas, "machine": self.machine, "hydraulic": self.hydraulic,
                "vision": self.vision, "tracking": self.tracking, "regulatory": self.regulatory}

    def status_all(self) -> dict[str, Any]:
        out = {}
        for k, v in self.all().items():
            st = v.status()
            st.setdefault("transport", self.transport(k))
            out[k] = st
        return out

    def readiness(self) -> dict[str, Any]:
        st = self.status_all()
        available = [k for k, v in st.items() if v["available"]]
        return {
            "ready": len(available) > 0,
            "available_models": available,
            "unavailable_models": [k for k, v in st.items() if not v["available"]],
            "models": st,
        }


_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry


def reset_registry() -> None:
    """Drop the cached registry (used by tests when config changes)."""
    global _registry
    _registry = None

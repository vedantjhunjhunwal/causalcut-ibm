"""Gas anomaly inference pipeline.

Wraps Niranjan's trained XGBoost gas classifier and Isolation Forest
drift detector into a single module that:

  1. Loads the .joblib artifacts (each contains a fitted scaler + model).
  2. Accepts a 128-dimensional sensor feature vector (the UCI Gas Sensor
     Array Drift feature set: 16 sensors × 8 features each).
  3. Classifies gas type (XGBoost) and flags anomalies/drift (IsoForest).
  4. Returns a dict matching Vedant's SafetyEventIn schema — ready to
     POST to /api/v1/events/ingest without any transformation.

The XGBoost model outputs:
  - Gas class label (0-5 mapping to GasType enum)
  - Prediction probability (used as `confidence`)

The IsoForest model outputs:
  - Anomaly label (1 = normal, -1 = anomaly)
  - Decision function score (lower = more anomalous)

These are combined:
  - If IsoForest says anomaly AND XGB confidence < 0.7 → sensor_drift event
  - Otherwise → gas_anomaly event with drift_detected flag
  - Severity is derived from anomaly score magnitude
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Gas label mapping — must match the order used during Nir's training.
# See .models/XGB Classifier/training_pipeline.py line 145.
GAS_CLASSES: list[str] = [
    "ethanol",
    "ethylene",
    "ammonia",
    "acetaldehyde",
    "acetone",
    "toluene",
]

# Sensor ID assignment — maps feature-vector position to sensor IDs.
# The dataset has 16 sensors (S1-S16), each with 8 features (dR, abs_dR,
# EMAi0.001, EMAi0.01, EMAi0.1, EMAd0.001, EMAd0.01, EMAd0.1).
SENSOR_IDS = [f"GS-{i:02d}" for i in range(1, 17)]

# Zone assignment for sensors (design doc §2.1: GS-01..GS-16 in zone-1)
DEFAULT_ZONE_ID = "zone-1"

# Severity mapping thresholds (anomaly_score → severity)
# IsoForest decision_function: more negative = more anomalous
SEVERITY_THRESHOLDS = [
    (-0.3, 0.9),   # very anomalous
    (-0.2, 0.7),
    (-0.1, 0.5),
    (-0.05, 0.3),
    (0.0, 0.15),
    (float("inf"), 0.05),  # normal
]

# Below this XGBoost confidence + IsoForest anomaly → emit sensor_drift
CONFIDENCE_DRIFT_THRESHOLD = 0.7


def _map_severity(anomaly_score: float) -> float:
    """Map IsoForest decision_function score to CAUSALCUT severity [0, 1].

    IsoForest decision_function returns negative values for anomalies
    (lower = more anomalous) and positive values for normal points.
    """
    for threshold, severity in SEVERITY_THRESHOLDS:
        if anomaly_score < threshold:
            return severity
    return 0.05


def _estimate_concentration(features: np.ndarray, sensor_index: int = 0) -> float:
    """Rough concentration estimate from the raw sensor features.

    The UCI dataset features are resistance changes (dR, abs_dR) and their
    exponential moving averages.  The absolute dR (index 1 per sensor, i.e.
    feature indices 1, 9, 17, ...) correlates roughly with concentration.
    This is an approximation — the actual ppm value would need the
    original calibration curves which aren't in the dataset.
    """
    # Use the abs_dR feature of the specified sensor (feature index = sensor_index * 8 + 1)
    feature_idx = sensor_index * 8 + 1
    if feature_idx < len(features):
        raw_value = float(features[feature_idx])
        # Scale to a plausible ppm range (the dataset values range ~0-10)
        return round(abs(raw_value) * 25.0, 1)
    return 0.0


def _detect_trend(features: np.ndarray, sensor_index: int = 0) -> str:
    """Infer trend from the EMA features.

    Each sensor has EMA-increase and EMA-decrease features at three
    time constants.  If the increase EMAs dominate, the signal is rising.
    """
    base = sensor_index * 8
    if base + 7 >= len(features):
        return "stable"

    ema_increase = sum(abs(features[base + i]) for i in [2, 3, 4])
    ema_decrease = sum(abs(features[base + i]) for i in [5, 6, 7])

    if ema_increase > ema_decrease * 1.3:
        return "rising"
    elif ema_decrease > ema_increase * 1.3:
        return "falling"
    return "stable"


def _get_sensor_feature_index(sensor_id: str, num_sensors: int = 16) -> int:
    """Safely map any arbitrary string sensor identifier (e.g. 'GS-MET-12', 'GS-03', 'HYD-FG-03')
    to a 0..15 feature block index without requiring the ID itself to be numeric."""
    import re
    digits = re.findall(r"\d+", str(sensor_id))
    if digits:
        try:
            val = int(digits[-1]) - 1
            return max(0, min(num_sensors - 1, val % num_sensors))
        except (ValueError, TypeError):
            pass
    return abs(hash(str(sensor_id))) % num_sensors


class GasInferencePipeline:
    """Loads Nir's XGBoost + IsoForest models and runs inference.

    Parameters
    ----------
    xgb_model_path : str | Path
        Path to the XGBoost .joblib artifact.
    isoforest_model_path : str | Path
        Path to the IsoForest .joblib artifact.
    zone_id : str
        Default zone for emitted events.
    """

    def __init__(
        self,
        xgb_model_path: str | Path | None = None,
        isoforest_model_path: str | Path | None = None,
        zone_id: str = DEFAULT_ZONE_ID,
    ) -> None:
        _base = Path(__file__).resolve().parent.parent.parent

        self.xgb_path = str(xgb_model_path or _base / ".models" / "XGB Classifier" / "model_1&2.joblib")
        self.iso_path = str(isoforest_model_path or _base / ".models" / "Isolation Forest Anomaly Detector" / "gas_sensor_isoforest_pipeline.joblib")
        self.zone_id = zone_id

        self._xgb_artifact = None
        self._iso_pipeline = None

    def _load_models(self) -> None:
        if self._xgb_artifact is not None:
            return

        try:
            import joblib
            import xgboost as xgb
        except ImportError as exc:
            raise ImportError("joblib and xgboost are required") from exc

        logger.info("Loading XGBoost artifact from %s", self.xgb_path)
        self._xgb_artifact = joblib.load(self.xgb_path)
        if not isinstance(self._xgb_artifact, dict):
            raise ValueError(f"Corrupt XGBoost artifact at {self.xgb_path}: expected dict, got {type(self._xgb_artifact)}")

        # Fail loudly if xgboost versions mismatch
        lib_vers = self._xgb_artifact.get("library_versions", {})
        trained_xgb = lib_vers.get("xgboost")
        if trained_xgb and trained_xgb != xgb.__version__:
            logger.warning(f"XGBoost version mismatch: model trained on {trained_xgb}, current is {xgb.__version__}")
            # we log warning here instead of crashing so the dashboard doesn't 500 error if they load an old one,
            # but ideally they should match.

        logger.info("Loading IsoForest pipeline from %s", self.iso_path)
        self._iso_pipeline = joblib.load(self.iso_path)

        self._xgb_reconstructed = None


    @property
    def xgb_scaler(self):
        self._load_models()
        return self._xgb_artifact.get("scaler", None)

    @property
    def xgb_model(self):
        self._load_models()
        if self._xgb_reconstructed is not None:
            return self._xgb_reconstructed

        # If it's an old artifact that still has 'model', return it safely
        if "model" in self._xgb_artifact:
            model_obj = self._xgb_artifact["model"]
            if hasattr(model_obj, "named_steps") and "classifier" in model_obj.named_steps:
                self._xgb_reconstructed = model_obj.named_steps["classifier"]
            else:
                self._xgb_reconstructed = model_obj
            return self._xgb_reconstructed

        # Reconstruct XGBClassifier natively from bytes
        import xgboost as xgb
        booster_bytes = self._xgb_artifact.get("model_bytes")
        classes = self._xgb_artifact.get("model_classes")

        if not booster_bytes:
            return None # Mock fallback if artifact didn't load properly

        import numpy as np
        self._xgb_reconstructed = xgb.XGBClassifier()
        self._xgb_reconstructed.load_model(bytearray(booster_bytes))
        self._xgb_reconstructed.classes_ = np.array(classes) if not isinstance(classes, np.ndarray) else classes
        self._xgb_reconstructed.n_classes_ = len(classes)
        
        return self._xgb_reconstructed

    @property
    def isoforest(self):
        self._load_models()
        return self._iso_pipeline

    @property
    def model_version(self) -> str:
        self._load_models()
        return self._xgb_artifact.get("version", "xgb-gas-v1.0.0")

    def infer(
        self,
        features: np.ndarray,
        sensor_id: str = "GS-03",
        zone_id: str | None = None,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        """Run inference on a single 128-dim feature vector.

        Returns a dict compatible with SafetyEventIn (ready to POST).
        """
        self._load_models()
        zone = zone_id or self.zone_id
        features = np.asarray(features, dtype=np.float64).reshape(1, -1)

        # --- XGBoost classification ---
        X_scaled = self.xgb_scaler.transform(features)
        gas_label = int(self.xgb_model.predict(X_scaled)[0])
        gas_proba = self.xgb_model.predict_proba(X_scaled)[0]
        gas_confidence = float(gas_proba[gas_label])
        
        # Use class_names from the artifact if available to avoid loading blindly
        artifact_classes = self._xgb_artifact.get("class_names")
        classes_list = artifact_classes if artifact_classes else GAS_CLASSES
        gas_name = classes_list[gas_label] if gas_label < len(classes_list) else f"unknown_{gas_label}"

        # --- IsoForest anomaly detection ---
        iso_label = int(self.isoforest.predict(features)[0])
        anomaly_score = float(self.isoforest.decision_function(features)[0])
        is_anomaly = iso_label == -1

        # --- Derive event type ---
        if is_anomaly and gas_confidence < CONFIDENCE_DRIFT_THRESHOLD:
            event_type = "sensor_drift"
        else:
            event_type = "gas_anomaly"

        # --- Derive metrics ---
        severity = _map_severity(anomaly_score) if is_anomaly else 0.05
        sensor_index = _get_sensor_feature_index(sensor_id)
        concentration = _estimate_concentration(features[0], sensor_index)
        trend = _detect_trend(features[0], sensor_index)

        # --- Build canonical event dict ---
        event = {
            "event_id": str(uuid.uuid4()),
            "zone_id": zone,
            "event_type": event_type,
            "event_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "value": {
                "sensor_id": sensor_id,
                "gas_type": gas_name,
                "concentration_ppm": concentration,
                "unit": "ppm",
                "trend": trend,
                "anomaly_score": round(anomaly_score, 4),
                "drift_detected": is_anomaly,
                "gas_class_label": gas_label,
                "gas_class_probabilities": {
                    classes_list[i]: round(float(gas_proba[i]), 4)
                    for i in range(len(gas_proba))
                    if i < len(classes_list)
                },
            },
            "severity": round(min(severity, 1.0), 4),
            "confidence": round(gas_confidence, 4),
            "uncertainty": round(1.0 - gas_confidence, 4),
            "source": "gas_anomaly_module_v2",
            "model_version": self.model_version,
            "provenance": batch_id or "UCI_GasSensorDrift",
            "information_class": "P",
            "synthetic_flag": False,
        }

        return event

    def infer_batch(
        self,
        feature_matrix: np.ndarray,
        sensor_ids: list[str] | None = None,
        zone_id: str | None = None,
        batch_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run inference on multiple rows. Each row is 128 features."""
        n = feature_matrix.shape[0]
        ids = sensor_ids or [f"GS-{(i % 16) + 1:02d}" for i in range(n)]
        return [
            self.infer(feature_matrix[i], sensor_id=ids[i], zone_id=zone_id, batch_id=batch_id)
            for i in range(n)
        ]


if __name__ == "__main__":
    import pandas as pd

    logging.basicConfig(level=logging.INFO)

    pipeline = GasInferencePipeline()

    # Load a few rows from Nir's dataset
    csv_path = Path(__file__).resolve().parent.parent.parent / ".datasets" / "gas_sensors_drift.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path, nrows=5)
        feature_cols = [c for c in df.columns if c not in ("label", "source_file")]
        X = df[feature_cols].values

        print(f"Running inference on {len(X)} samples...\n")
        for i, row in enumerate(X):
            event = pipeline.infer(row, sensor_id=f"GS-{i+1:02d}")
            print(f"Sample {i}: {event['event_type']}")
            print(f"  gas: {event['value']['gas_type']} (conf={event['confidence']})")
            print(f"  drift: {event['value']['drift_detected']} (score={event['value']['anomaly_score']})")
            print(f"  severity: {event['severity']}")
            print()
    else:
        print(f"Dataset not found at {csv_path}")

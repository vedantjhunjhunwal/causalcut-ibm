"""Tests for gas inference pipeline.

Covers: model loading, output schema compliance, severity mapping,
information class enforcement, and batch inference.

These tests load the actual XGBoost + IsoForest models from .models/
so they double as integration tests for Nir's trained artifacts.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

# Skip all tests if model files aren't available
_BASE = Path(__file__).resolve().parent.parent
_XGB_PATH = _BASE / ".models" / "XGB Classifier" / "model_1&2.joblib"
_ISO_PATH = _BASE / ".models" / "Isolation Forest Anomaly Detector" / "gas_sensor_isoforest_pipeline.joblib"
_MODELS_AVAILABLE = _XGB_PATH.exists() and _ISO_PATH.exists()

pytestmark = pytest.mark.skipif(
    not _MODELS_AVAILABLE,
    reason="Model artifacts not found — run from repo root with .models/ present",
)

from src.inference.gas_inference import (
    GAS_CLASSES,
    GasInferencePipeline,
    _detect_trend,
    _estimate_concentration,
    _map_severity,
)


@pytest.fixture(scope="module")
def pipeline():
    return GasInferencePipeline(
        xgb_model_path=str(_XGB_PATH),
        isoforest_model_path=str(_ISO_PATH),
    )


@pytest.fixture(scope="module")
def sample_features():
    """Load the first 10 rows from the gas sensor CSV."""
    csv_path = _BASE / ".datasets" / "gas_sensors_drift.csv"
    if not csv_path.exists():
        pytest.skip("gas_sensors_drift.csv not found")

    import pandas as pd

    df = pd.read_csv(csv_path, nrows=10)
    feature_cols = [c for c in df.columns if c not in ("label", "source_file")]
    return df[feature_cols].values


# ------------------------------------------------------------------ #
# Severity mapping
# ------------------------------------------------------------------ #
class TestSeverityMapping:
    def test_very_anomalous(self):
        assert _map_severity(-0.5) == 0.9

    def test_normal(self):
        assert _map_severity(0.1) == 0.05

    def test_borderline(self):
        sev = _map_severity(-0.1)
        assert 0.3 <= sev <= 0.5


# ------------------------------------------------------------------ #
# Feature helpers
# ------------------------------------------------------------------ #
class TestFeatureHelpers:
    def test_estimate_concentration_positive(self):
        features = np.random.randn(128)
        conc = _estimate_concentration(features, sensor_index=0)
        assert conc >= 0.0

    def test_detect_trend_returns_valid(self):
        features = np.random.randn(128)
        trend = _detect_trend(features, sensor_index=0)
        assert trend in ("rising", "falling", "stable")


# ------------------------------------------------------------------ #
# Pipeline inference
# ------------------------------------------------------------------ #
class TestGasInferencePipeline:
    def test_single_inference_schema(self, pipeline, sample_features):
        event = pipeline.infer(sample_features[0], sensor_id="GS-03")

        # Required fields for SafetyEventIn
        assert event["zone_id"] in ("zone-1", "zone-2", "zone-3", "zone-4", "zone-5", "zone-6")
        assert event["event_type"] in ("gas_anomaly", "sensor_drift")
        assert "event_time" in event
        assert "event_id" in event

        # Value payload
        v = event["value"]
        assert "sensor_id" in v
        assert "gas_type" in v
        assert v["gas_type"] in GAS_CLASSES
        assert "concentration_ppm" in v
        assert isinstance(v["concentration_ppm"], float)
        assert "drift_detected" in v
        assert isinstance(v["drift_detected"], bool)
        assert "anomaly_score" in v

        # Scoring
        assert 0.0 <= event["severity"] <= 1.0
        assert 0.0 <= event["confidence"] <= 1.0
        assert 0.0 <= event["uncertainty"] <= 1.0
        assert abs(event["confidence"] + event["uncertainty"] - 1.0) < 0.01

        # Provenance
        assert event["source"] == "gas_anomaly_module_v2"
        assert event["model_version"] is not None
        assert event["information_class"] == "M"
        assert event["synthetic_flag"] is False

    def test_information_class_always_measured(self, pipeline, sample_features):
        """Gas sensor readings are always [M] — measured observations."""
        for i in range(min(5, len(sample_features))):
            event = pipeline.infer(sample_features[i])
            assert event["information_class"] == "M"

    def test_severity_bounded(self, pipeline, sample_features):
        for i in range(min(5, len(sample_features))):
            event = pipeline.infer(sample_features[i])
            assert 0.0 <= event["severity"] <= 1.0

    def test_batch_inference(self, pipeline, sample_features):
        events = pipeline.infer_batch(sample_features[:5])
        assert len(events) == 5
        assert all(e["event_type"] in ("gas_anomaly", "sensor_drift") for e in events)

    def test_sensor_ids_in_batch(self, pipeline, sample_features):
        sensor_ids = ["GS-01", "GS-05", "GS-10"]
        events = pipeline.infer_batch(
            sample_features[:3],
            sensor_ids=sensor_ids,
        )
        for event, expected_id in zip(events, sensor_ids):
            assert event["value"]["sensor_id"] == expected_id

    def test_gas_class_probabilities_sum_to_one(self, pipeline, sample_features):
        event = pipeline.infer(sample_features[0])
        probs = event["value"]["gas_class_probabilities"]
        total = sum(probs.values())
        assert abs(total - 1.0) < 0.01

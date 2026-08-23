"""Unit tests for app.engine.drift_monitor.SensorDriftMonitor.

Real: exercises the actual ADWIN detector from river when installed.
Skipped: gracefully asserts the degraded contract when river is absent,
rather than being skipped outright, since that degraded path is itself part
of the contract this module promises (same pattern as the rest of the
project's optional-dependency handling).
"""

from __future__ import annotations

import random

from app.engine.drift_monitor import DRIFT_AVAILABLE, SensorDriftMonitor


def test_insufficient_history_is_not_drift():
    monitor = SensorDriftMonitor()
    result = monitor.check("GS-03", [1.0, 2.0, 3.0])
    assert result["drift_detected"] is False
    assert result["samples_checked"] == 3


def test_degraded_contract_when_river_missing(monkeypatch):
    monkeypatch.setattr("app.engine.drift_monitor.DRIFT_AVAILABLE", False)
    monitor = SensorDriftMonitor()
    result = monitor.check("GS-03", [1.0] * 50)
    assert result["available"] is False
    assert result["drift_detected"] is None


def test_stable_signal_reports_no_drift():
    if not DRIFT_AVAILABLE:
        return  # covered by the degraded-contract test above
    random.seed(7)
    readings = [random.gauss(50.0, 1.0) for _ in range(150)]
    monitor = SensorDriftMonitor()
    result = monitor.check("GS-03", readings)
    assert result["available"] is True
    assert result["drift_detected"] is False


def test_shifted_signal_is_flagged():
    if not DRIFT_AVAILABLE:
        return
    random.seed(7)
    readings = [random.gauss(50.0, 1.0) for _ in range(100)]
    readings += [random.gauss(500.0, 5.0) for _ in range(100)]
    monitor = SensorDriftMonitor()
    result = monitor.check("GS-03", readings)
    assert result["available"] is True
    assert result["drift_detected"] is True
    assert result["drift_detected_at_sample"] is not None

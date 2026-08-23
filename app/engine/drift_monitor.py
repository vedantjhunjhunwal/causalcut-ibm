"""Per-sensor concept-drift monitoring for the agent's ``check_sensor_drift`` tool.

Relationship to ``realtime/drift_detector.py``
-----------------------------------------------
That module wraps ADWIN (river) over the full 128-dimensional raw gas
feature vector (16 sensors x 8 features), one ADWIN instance per feature.
It is correct, but it is standalone: nothing in the ingestion spine stores
that raw 128-dim vector once a prediction has been made, so it cannot be fed
from historical data today. Wiring it up for real would mean persisting the
raw feature array alongside every gas prediction -- a real change to the
ingestion schema, out of scope for the agent itself.

What IS available, today, in SQLite: a scalar time series per physical
sensor via ``SensorTelemetryRepository.history(sensor_id)`` -- the same data
``GET /state/sensors/{id}/history`` already serves. This module applies the
same algorithm (ADWIN) at that coarser granularity: one detector per
sensor_id, fed from its scalar value history. It is a legitimate, honest
degrade of the original design to the data that actually exists, not a
replacement for it -- if the raw 128-dim vector is ever persisted, the
richer per-feature detector in ``realtime/drift_detector.py`` should be
preferred and this module can proxy to it.

Degrades cleanly (``available=False``) if ``river`` is not installed, in
keeping with the project's existing pattern for optional dependencies
(vision/tracking, FAISS RAG).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from river.drift import ADWIN
    DRIFT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when river is absent
    ADWIN = None  # type: ignore[assignment]
    DRIFT_AVAILABLE = False


@dataclass
class SensorDriftMonitor:
    """One ADWIN detector per sensor_id, replayed over its reading history.

    Stateless across calls by design: each ``check`` replays the requested
    history from scratch, so results are deterministic and there is no
    per-process state to leak between requests or go stale.
    """

    delta: float = 0.002
    _detectors: dict[str, Any] = field(default_factory=dict, repr=False)

    def check(self, sensor_id: str, readings: list[float]) -> dict[str, Any]:
        if not DRIFT_AVAILABLE:
            return {
                "available": False,
                "sensor_id": sensor_id,
                "reason": "river package not installed (pip install river)",
                "drift_detected": None,
                "samples_checked": 0,
            }

        if len(readings) < 10:
            return {
                "available": True,
                "sensor_id": sensor_id,
                "drift_detected": False,
                "samples_checked": len(readings),
                "reason": "insufficient history for a meaningful drift check (<10 samples)",
            }

        detector = ADWIN(delta=self.delta)
        drift_at: int | None = None
        for i, value in enumerate(readings):
            detector.update(value)
            if detector.drift_detected and drift_at is None:
                drift_at = i

        return {
            "available": True,
            "sensor_id": sensor_id,
            "drift_detected": drift_at is not None,
            "drift_detected_at_sample": drift_at,
            "samples_checked": len(readings),
            "note": (
                "Drift flags a statistically significant shift in the sensor's "
                "value distribution -- treat any model prediction drawing on "
                "this sensor with reduced confidence until re-verified."
                if drift_at is not None else
                "No distributional shift detected over the checked window."
            ),
        }

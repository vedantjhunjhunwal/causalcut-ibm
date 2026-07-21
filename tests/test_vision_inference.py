"""Tests for vision inference pipeline.

Covers: canonical event generation from TrackedWorker objects,
PPE violation detection, debouncing, and event type selection.
Mocks the tracker so no YOLO model is needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.inference.vision_inference import (
    DEBOUNCE_WINDOW,
    VisionInferencePipeline,
    _ppe_state_key,
)
from src.inference.vision_tracker import TrackedWorker


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #
def _make_worker(
    track_id: int = 1,
    worker_id: str = "W-001",
    zone_id: str = "zone-1",
    hard_hat: bool = True,
    safety_vest: bool = True,
) -> TrackedWorker:
    return TrackedWorker(
        track_id=track_id,
        worker_id=worker_id,
        zone_id=zone_id,
        camera_id="CAM-01",
        bbox_xyxy=(10, 20, 200, 400),
        confidence=0.92,
        ppe={
            "hard_hat": hard_hat,
            "safety_vest": safety_vest,
            "safety_goggles": None,
            "gloves": None,
        },
    )


# ------------------------------------------------------------------ #
# PPE state key
# ------------------------------------------------------------------ #
class TestPPEStateKey:
    def test_deterministic(self):
        ppe = {"hard_hat": True, "safety_vest": False, "safety_goggles": None, "gloves": None}
        k1 = _ppe_state_key(ppe)
        k2 = _ppe_state_key(ppe)
        assert k1 == k2

    def test_different_states_different_keys(self):
        ppe_a = {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}
        ppe_b = {"hard_hat": False, "safety_vest": True, "safety_goggles": None, "gloves": None}
        assert _ppe_state_key(ppe_a) != _ppe_state_key(ppe_b)


# ------------------------------------------------------------------ #
# Event generation
# ------------------------------------------------------------------ #
class TestVisionInferencePipeline:
    def _make_pipeline(self) -> VisionInferencePipeline:
        """Create a pipeline without loading YOLO."""
        p = VisionInferencePipeline.__new__(VisionInferencePipeline)
        p.debounce = True
        p._last_emitted = {}
        p.tracker = None  # not used in process_tracked_workers
        return p

    def test_compliant_worker_generates_presence_event(self):
        p = self._make_pipeline()
        worker = _make_worker(hard_hat=True, safety_vest=True)
        events = p.process_tracked_workers([worker])

        assert len(events) == 1
        assert events[0]["event_type"] == "worker_presence"
        assert events[0]["worker_id"] == "W-001"
        assert events[0]["zone_id"] == "zone-1"
        assert events[0]["information_class"] == "M"
        assert events[0]["severity"] == 0.0

    def test_non_compliant_generates_violation_event(self):
        p = self._make_pipeline()
        worker = _make_worker(hard_hat=False, safety_vest=True)
        events = p.process_tracked_workers([worker])

        assert len(events) == 1
        assert events[0]["event_type"] == "ppe_violation"
        assert events[0]["severity"] == 0.62
        assert "missing" in events[0]["value"]
        assert "hard_hat" in events[0]["value"]["missing"]

    def test_both_ppe_missing(self):
        p = self._make_pipeline()
        worker = _make_worker(hard_hat=False, safety_vest=False)
        events = p.process_tracked_workers([worker])

        assert events[0]["event_type"] == "ppe_violation"
        missing = events[0]["value"]["missing"]
        assert "hard_hat" in missing
        assert "safety_vest" in missing

    def test_ppe_dict_in_value(self):
        p = self._make_pipeline()
        worker = _make_worker(hard_hat=True, safety_vest=False)
        events = p.process_tracked_workers([worker])

        ppe = events[0]["value"]["ppe"]
        assert ppe["hard_hat"] is True
        assert ppe["safety_vest"] is False
        assert ppe["safety_goggles"] is None  # undetectable

    def test_multiple_workers(self):
        p = self._make_pipeline()
        workers = [
            _make_worker(track_id=1, worker_id="W-001", hard_hat=True, safety_vest=True),
            _make_worker(track_id=2, worker_id="W-002", hard_hat=False, safety_vest=True),
        ]
        events = p.process_tracked_workers(workers)

        assert len(events) == 2
        types = {e["worker_id"]: e["event_type"] for e in events}
        assert types["W-001"] == "worker_presence"
        assert types["W-002"] == "ppe_violation"

    # ---------------------------------------------------------------- #
    # Debouncing
    # ---------------------------------------------------------------- #
    def test_duplicate_debounced(self):
        """Same worker, same zone, same PPE → no duplicate event."""
        p = self._make_pipeline()
        worker = _make_worker()

        events1 = p.process_tracked_workers([worker])
        assert len(events1) == 1

        events2 = p.process_tracked_workers([worker])
        assert len(events2) == 0  # debounced

    def test_ppe_change_breaks_debounce(self):
        """PPE state change → new event even within debounce window."""
        p = self._make_pipeline()

        worker_ok = _make_worker(hard_hat=True, safety_vest=True)
        events1 = p.process_tracked_workers([worker_ok])
        assert len(events1) == 1
        assert events1[0]["event_type"] == "worker_presence"

        worker_bad = _make_worker(hard_hat=False, safety_vest=True)
        events2 = p.process_tracked_workers([worker_bad])
        assert len(events2) == 1
        assert events2[0]["event_type"] == "ppe_violation"

    def test_zone_change_breaks_debounce(self):
        """Zone change → new event even with same PPE state."""
        p = self._make_pipeline()

        worker_z1 = _make_worker(zone_id="zone-1")
        events1 = p.process_tracked_workers([worker_z1])
        assert len(events1) == 1

        worker_z2 = _make_worker(zone_id="zone-2")
        events2 = p.process_tracked_workers([worker_z2])
        assert len(events2) == 1  # new zone → emitted

    def test_debounce_disabled(self):
        """With debounce=False, every call emits."""
        p = self._make_pipeline()
        p.debounce = False

        worker = _make_worker()
        events1 = p.process_tracked_workers([worker])
        events2 = p.process_tracked_workers([worker])
        assert len(events1) == 1
        assert len(events2) == 1  # not debounced

    def test_reset_debounce(self):
        p = self._make_pipeline()
        worker = _make_worker()

        p.process_tracked_workers([worker])  # emitted
        events = p.process_tracked_workers([worker])  # debounced
        assert len(events) == 0

        p.reset_debounce()
        events = p.process_tracked_workers([worker])  # emitted again
        assert len(events) == 1

    # ---------------------------------------------------------------- #
    # Schema compliance
    # ---------------------------------------------------------------- #
    def test_event_schema_completeness(self):
        """All required SafetyEventIn fields are present."""
        p = self._make_pipeline()
        worker = _make_worker()
        events = p.process_tracked_workers([worker])
        event = events[0]

        required_fields = [
            "event_id", "zone_id", "event_type", "event_time",
            "worker_id", "value", "confidence", "source",
            "model_version", "information_class", "synthetic_flag",
        ]
        for f in required_fields:
            assert f in event, f"Missing field: {f}"

    def test_confidence_bounded(self):
        p = self._make_pipeline()
        worker = _make_worker()
        events = p.process_tracked_workers([worker])
        assert 0.0 <= events[0]["confidence"] <= 1.0
        assert 0.0 <= events[0]["uncertainty"] <= 1.0

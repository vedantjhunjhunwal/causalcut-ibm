"""Tests for ByteTrack vision tracker.

Covers: PPE-to-person association via IoU/containment, worker ID
assignment stability, TrackedWorker compliance logic, and edge cases
(no persons, no PPE items, overlapping boxes).
"""

from __future__ import annotations

import numpy as np
import pytest

from src.inference.vision_tracker import (
    ALL_PPE_ITEMS,
    DETECTABLE_PPE,
    TrackedWorker,
    VisionTracker,
    _associate_ppe,
    _containment_ratio,
    _iou,
)
from src.inference.yolo_detector import Detection


# ------------------------------------------------------------------ #
# Geometry helpers
# ------------------------------------------------------------------ #
class TestIoU:
    def test_perfect_overlap(self):
        assert _iou((0, 0, 100, 100), (0, 0, 100, 100)) == pytest.approx(1.0)

    def test_no_overlap(self):
        assert _iou((0, 0, 50, 50), (100, 100, 200, 200)) == 0.0

    def test_partial_overlap(self):
        iou = _iou((0, 0, 100, 100), (50, 50, 150, 150))
        # intersection = 50*50=2500, union = 10000+10000-2500=17500
        assert iou == pytest.approx(2500 / 17500, abs=0.01)

    def test_degenerate_box(self):
        assert _iou((0, 0, 0, 0), (0, 0, 100, 100)) == 0.0


class TestContainment:
    def test_fully_inside(self):
        ratio = _containment_ratio((20, 20, 80, 80), (0, 0, 100, 100))
        assert ratio == pytest.approx(1.0)

    def test_fully_outside(self):
        ratio = _containment_ratio((200, 200, 300, 300), (0, 0, 100, 100))
        assert ratio == 0.0

    def test_half_inside(self):
        # inner: 50x100 area, half overlapping with outer
        ratio = _containment_ratio((50, 0, 100, 100), (0, 0, 75, 100))
        # overlap: 25*100=2500, inner area: 50*100=5000
        assert ratio == pytest.approx(0.5)


# ------------------------------------------------------------------ #
# PPE association
# ------------------------------------------------------------------ #
class TestPPEAssociation:
    def test_hard_hat_on_person_head(self):
        """Hard hat bbox overlaps top of person bbox → associated."""
        persons = [
            {"bbox_xyxy": (10, 20, 200, 400), "track_id": 1},
        ]
        ppe_items = [
            Detection(class_name="hard_hat", confidence=0.85, bbox_xyxy=(30, 10, 80, 50)),
        ]
        result = _associate_ppe(persons, ppe_items)
        assert result[0]["ppe"]["hard_hat"] is True
        assert result[0]["ppe"]["safety_vest"] is False  # not detected

    def test_vest_on_person_torso(self):
        persons = [
            {"bbox_xyxy": (10, 20, 200, 400), "track_id": 1},
        ]
        ppe_items = [
            Detection(class_name="safety_vest", confidence=0.75, bbox_xyxy=(20, 80, 190, 250)),
        ]
        result = _associate_ppe(persons, ppe_items)
        assert result[0]["ppe"]["safety_vest"] is True

    def test_ppe_far_from_person_not_associated(self):
        """PPE bbox far from any person → dropped (not associated)."""
        persons = [
            {"bbox_xyxy": (10, 20, 200, 400), "track_id": 1},
        ]
        ppe_items = [
            Detection(class_name="hard_hat", confidence=0.85, bbox_xyxy=(500, 500, 550, 530)),
        ]
        result = _associate_ppe(persons, ppe_items)
        assert result[0]["ppe"]["hard_hat"] is False

    def test_multiple_persons_nearest_wins(self):
        """PPE item between two persons → assigned to the one with higher containment."""
        persons = [
            {"bbox_xyxy": (0, 0, 100, 200), "track_id": 1},
            {"bbox_xyxy": (200, 0, 300, 200), "track_id": 2},
        ]
        # Hard hat overlapping person 1's head area
        ppe_items = [
            Detection(class_name="hard_hat", confidence=0.85, bbox_xyxy=(20, 0, 60, 30)),
        ]
        result = _associate_ppe(persons, ppe_items)
        assert result[0]["ppe"]["hard_hat"] is True   # person 1 gets it
        assert result[1]["ppe"]["hard_hat"] is False   # person 2 doesn't

    def test_no_ppe_all_absent(self):
        persons = [
            {"bbox_xyxy": (10, 20, 200, 400), "track_id": 1},
        ]
        result = _associate_ppe(persons, [])
        assert result[0]["ppe"]["hard_hat"] is False
        assert result[0]["ppe"]["safety_vest"] is False
        assert result[0]["ppe"]["safety_goggles"] is None  # undetectable
        assert result[0]["ppe"]["gloves"] is None

    def test_no_persons(self):
        result = _associate_ppe([], [Detection(class_name="hard_hat", confidence=0.9, bbox_xyxy=(0, 0, 50, 50))])
        assert result == []


# ------------------------------------------------------------------ #
# TrackedWorker
# ------------------------------------------------------------------ #
class TestTrackedWorker:
    def test_compliant_worker(self):
        w = TrackedWorker(
            track_id=1, worker_id="W-001", zone_id="zone-1", camera_id="CAM-01",
            bbox_xyxy=(0, 0, 100, 200), confidence=0.95,
            ppe={"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None},
        )
        assert w.is_compliant is True
        assert w.missing_ppe == []

    def test_non_compliant_missing_hat(self):
        w = TrackedWorker(
            track_id=1, worker_id="W-001", zone_id="zone-1", camera_id="CAM-01",
            bbox_xyxy=(0, 0, 100, 200), confidence=0.95,
            ppe={"hard_hat": False, "safety_vest": True, "safety_goggles": None, "gloves": None},
        )
        assert w.is_compliant is False
        assert "hard_hat" in w.missing_ppe

    def test_non_compliant_missing_vest(self):
        w = TrackedWorker(
            track_id=1, worker_id="W-001", zone_id="zone-1", camera_id="CAM-01",
            bbox_xyxy=(0, 0, 100, 200), confidence=0.95,
            ppe={"hard_hat": True, "safety_vest": False, "safety_goggles": None, "gloves": None},
        )
        assert w.is_compliant is False
        assert "safety_vest" in w.missing_ppe

    def test_to_dict(self):
        w = TrackedWorker(
            track_id=5, worker_id="W-005", zone_id="zone-2", camera_id="CAM-03",
            bbox_xyxy=(10.5, 20.5, 110.5, 220.5), confidence=0.9123,
            ppe={"hard_hat": True, "safety_vest": False, "safety_goggles": None, "gloves": None},
        )
        d = w.to_dict()
        assert d["worker_id"] == "W-005"
        assert d["is_compliant"] is False
        assert "safety_vest" in d["missing_ppe"]
        assert d["confidence"] == 0.9123


# ------------------------------------------------------------------ #
# Worker ID stability
# ------------------------------------------------------------------ #
class TestWorkerIDAssignment:
    def test_same_track_gets_same_worker_id(self):
        """The tracker should assign the same W-XXX ID for the same track_id."""
        tracker = VisionTracker.__new__(VisionTracker)
        tracker._track_to_worker = {}
        tracker._next_worker_num = 1

        id1 = tracker._get_worker_id(42)
        id2 = tracker._get_worker_id(42)
        assert id1 == id2

    def test_different_tracks_get_different_ids(self):
        tracker = VisionTracker.__new__(VisionTracker)
        tracker._track_to_worker = {}
        tracker._next_worker_num = 1

        id1 = tracker._get_worker_id(1)
        id2 = tracker._get_worker_id(2)
        assert id1 != id2
        assert id1 == "W-001"
        assert id2 == "W-002"

    def test_ids_survive_across_calls(self):
        tracker = VisionTracker.__new__(VisionTracker)
        tracker._track_to_worker = {}
        tracker._next_worker_num = 1

        tracker._get_worker_id(10)
        tracker._get_worker_id(20)
        tracker._get_worker_id(30)

        assert tracker._get_worker_id(20) == "W-002"
        assert tracker._get_worker_id(10) == "W-001"

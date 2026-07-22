"""Tests for YOLOv8 detector wrapper.

Covers: model loading, detection output format, confidence filtering,
empty-frame handling, and class mapping.  Uses mock YOLO results to
avoid requiring actual model weights in CI.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.inference.yolo_detector import (
    DEFAULT_CLASS_MAP,
    Detection,
    DetectionResult,
    YOLODetector,
)


# ------------------------------------------------------------------ #
# Detection dataclass
# ------------------------------------------------------------------ #
class TestDetection:
    def test_area_calculation(self):
        d = Detection(class_name="person", confidence=0.9, bbox_xyxy=(10, 20, 110, 220))
        assert d.area == 100 * 200

    def test_area_zero_for_degenerate_box(self):
        d = Detection(class_name="person", confidence=0.9, bbox_xyxy=(50, 50, 50, 50))
        assert d.area == 0.0

    def test_to_dict_round_trips(self):
        d = Detection(class_name="hard_hat", confidence=0.876543, bbox_xyxy=(1.111, 2.222, 3.333, 4.444), class_id=0)
        out = d.to_dict()
        assert out["class_name"] == "hard_hat"
        assert out["confidence"] == 0.8765
        assert all(isinstance(v, float) for v in out["bbox_xyxy"])

    def test_frozen(self):
        d = Detection(class_name="person", confidence=0.9, bbox_xyxy=(0, 0, 100, 100))
        with pytest.raises(AttributeError):
            d.class_name = "vest"


# ------------------------------------------------------------------ #
# DetectionResult
# ------------------------------------------------------------------ #
class TestDetectionResult:
    def test_persons_and_ppe_split(self):
        dets = [
            Detection(class_name="person", confidence=0.9, bbox_xyxy=(0, 0, 100, 200)),
            Detection(class_name="hard_hat", confidence=0.8, bbox_xyxy=(20, 0, 60, 30)),
            Detection(class_name="safety_vest", confidence=0.7, bbox_xyxy=(10, 60, 90, 150)),
            Detection(class_name="person", confidence=0.85, bbox_xyxy=(200, 0, 300, 200)),
        ]
        result = DetectionResult(detections=dets)
        assert len(result.persons) == 2
        assert len(result.ppe_items) == 2

    def test_empty_result(self):
        result = DetectionResult()
        assert result.persons == []
        assert result.ppe_items == []
        assert result.to_dict()["person_count"] == 0


# ------------------------------------------------------------------ #
# YOLODetector (with mocked model)
# ------------------------------------------------------------------ #
class MockBox:
    """Mimics ultralytics Boxes for a single detection."""

    def __init__(self, cls_id, conf, xyxy):
        import torch

        self.cls = torch.tensor([cls_id])
        self.conf = torch.tensor([conf])
        self.xyxy = torch.tensor([xyxy])

    def __len__(self):
        return 1


class MockBoxes:
    """Mimics ultralytics Boxes container."""

    def __init__(self, boxes_data: list):
        import torch

        if not boxes_data:
            self.cls = torch.tensor([])
            self.conf = torch.tensor([])
            self.xyxy = torch.tensor([]).reshape(0, 4)
            self._len = 0
        else:
            self.cls = torch.tensor([b[0] for b in boxes_data])
            self.conf = torch.tensor([b[1] for b in boxes_data])
            self.xyxy = torch.tensor([b[2] for b in boxes_data])
            self._len = len(boxes_data)

    def __len__(self):
        return self._len


class MockResult:
    def __init__(self, boxes_data):
        self.boxes = MockBoxes(boxes_data)
        self.speed = {"preprocess": 1.0, "inference": 5.0, "postprocess": 1.0}


class TestYOLODetector:
    def _make_detector_with_mock(self, boxes_data):
        """Create a detector with a mocked model that returns fixed boxes."""
        detector = YOLODetector.__new__(YOLODetector)
        detector.model_path = "mock"
        detector.class_map = dict(DEFAULT_CLASS_MAP)
        detector.thresholds = {"person": 0.50, "hard_hat": 0.35, "safety_vest": 0.35}
        detector.device = "cpu"
        detector.imgsz = 640

        class FakeModel:
            def predict(self, **kwargs):
                return [MockResult(boxes_data)]

        detector._model = FakeModel()
        return detector

    def test_detect_returns_correct_format(self):
        boxes = [
            (1, 0.92, [10, 20, 200, 400]),   # person
            (0, 0.85, [30, 5, 80, 40]),       # hard_hat
        ]
        detector = self._make_detector_with_mock(boxes)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = detector.detect(frame)

        assert isinstance(result, DetectionResult)
        assert len(result.detections) == 2
        assert result.persons[0].class_name == "person"
        assert result.ppe_items[0].class_name == "hard_hat"

    def test_confidence_filtering(self):
        boxes = [
            (1, 0.92, [10, 20, 200, 400]),   # person: above 0.50 → kept
            (0, 0.20, [30, 5, 80, 40]),       # hard_hat: below 0.35 → filtered
            (2, 0.40, [10, 80, 190, 300]),    # safety_vest: above 0.35 → kept
        ]
        detector = self._make_detector_with_mock(boxes)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = detector.detect(frame)

        assert len(result.detections) == 2
        class_names = {d.class_name for d in result.detections}
        assert "hard_hat" not in class_names  # filtered out

    def test_conf_override(self):
        boxes = [
            (1, 0.45, [10, 20, 200, 400]),
        ]
        detector = self._make_detector_with_mock(boxes)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # With default threshold (0.50 for person) → filtered
        result_default = detector.detect(frame)
        assert len(result_default.detections) == 0

        # With override at 0.40 → kept
        result_override = detector.detect(frame, conf_override=0.40)
        assert len(result_override.detections) == 1

    def test_empty_frame(self):
        detector = self._make_detector_with_mock([])
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = detector.detect(frame)
        assert result.detections == []
        assert result.inference_ms >= 0

    def test_class_map_respected(self):
        boxes = [(0, 0.9, [0, 0, 50, 50])]
        detector = self._make_detector_with_mock(boxes)
        detector.class_map = {0: "custom_class"}
        detector.thresholds = {"custom_class": 0.3}

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = detector.detect(frame)
        assert result.detections[0].class_name == "custom_class"

    def test_batch_detect(self):
        boxes = [(1, 0.9, [10, 20, 200, 400])]
        detector = self._make_detector_with_mock(boxes)
        frames = [np.zeros((480, 640, 3), dtype=np.uint8)] * 3
        results = detector.detect_batch(frames)
        assert len(results) == 3
        assert all(isinstance(r, DetectionResult) for r in results)

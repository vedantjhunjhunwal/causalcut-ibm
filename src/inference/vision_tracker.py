"""ByteTrack-based worker tracking with PPE association.

Takes raw YOLO detections frame-by-frame and:
  1. Tracks *person* detections across frames (stable track IDs).
  2. Associates PPE item detections (hard_hat, safety_vest) with the
     nearest tracked person via IoU overlap.
  3. Outputs TrackedWorker objects ready for the vision inference pipeline
     to convert into canonical SafetyEventIn dicts.

The tracker itself is from the ``supervision`` library (sv.ByteTrack),
which is a pure-Python port of the original ByteTrack paper.  We don't
need to install the C++ version — at our camera count (≤10) the Python
implementation is more than fast enough.

Usage:
    tracker = VisionTracker("models/yolov8_ppe.pt")
    for frame in camera_feed:
        workers = tracker.process_frame(frame, camera_id="CAM-01", zone_id="zone-1")
        for w in workers:
            print(w.worker_id, w.ppe, w.is_compliant)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from src.inference.yolo_detector import Detection, DetectionResult, YOLODetector

logger = logging.getLogger(__name__)

# PPE items that the model can detect.  Items not in this list are
# reported as None (unknown) rather than False (absent) — we can't
# detect gloves or goggles with this model.
DETECTABLE_PPE = {"hard_hat", "safety_vest"}

# All PPE items the canonical schema knows about.
ALL_PPE_ITEMS = {"hard_hat", "safety_vest", "safety_goggles", "gloves"}

# IoU threshold for associating a PPE item bbox with a person bbox.
PPE_ASSOCIATION_IOU_THRESHOLD = 0.05

# Vertical overlap: a hard hat should be near the top of the person bbox.
# We use a more generous containment check instead of strict IoU for small
# items like hard hats that sit on top of the person's head.
PPE_CONTAINMENT_THRESHOLD = 0.3


@dataclass
class TrackedWorker:
    """One tracked person in a single frame, with associated PPE."""

    track_id: int
    worker_id: str               # "W-003" format
    zone_id: str
    camera_id: str
    bbox_xyxy: tuple[float, ...]
    confidence: float
    ppe: dict[str, bool | None]  # True=present, False=absent, None=undetectable
    frame_index: int = 0

    @property
    def is_compliant(self) -> bool:
        """A worker is compliant if all *detectable* PPE items are present."""
        return all(
            self.ppe.get(item) is True
            for item in DETECTABLE_PPE
        )

    @property
    def missing_ppe(self) -> list[str]:
        return [
            item for item in DETECTABLE_PPE
            if self.ppe.get(item) is False
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "worker_id": self.worker_id,
            "zone_id": self.zone_id,
            "camera_id": self.camera_id,
            "bbox_xyxy": [round(v, 1) for v in self.bbox_xyxy],
            "confidence": round(self.confidence, 4),
            "ppe": dict(self.ppe),
            "is_compliant": self.is_compliant,
            "missing_ppe": self.missing_ppe,
        }


def _iou(box_a: tuple, box_b: tuple) -> float:
    """Compute Intersection-over-Union for two (x1, y1, x2, y2) boxes."""
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])

    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    union = area_a + area_b - inter

    return inter / union if union > 0 else 0.0


def _containment_ratio(inner: tuple, outer: tuple) -> float:
    """Fraction of `inner` box area that falls inside `outer` box."""
    x1 = max(inner[0], outer[0])
    y1 = max(inner[1], outer[1])
    x2 = min(inner[2], outer[2])
    y2 = min(inner[3], outer[3])

    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    inner_area = max(0.0, inner[2] - inner[0]) * max(0.0, inner[3] - inner[1])
    return inter / inner_area if inner_area > 0 else 0.0


def _associate_ppe(
    persons: list[dict],
    ppe_items: list[Detection],
) -> list[dict]:
    """Associate PPE detections with the nearest tracked person.

    For each PPE detection, finds the person whose bounding box contains
    it most (by containment ratio).  If no person contains it above the
    threshold, the PPE item is dropped (likely a false positive).
    """
    # Start with all detectable PPE set to False (absent)
    for p in persons:
        ppe_state = {}
        for item in ALL_PPE_ITEMS:
            if item in DETECTABLE_PPE:
                ppe_state[item] = False
            else:
                ppe_state[item] = None  # can't detect this item
        p["ppe"] = ppe_state

    for ppe_det in ppe_items:
        best_person = None
        best_score = 0.0

        for p in persons:
            person_box = p["bbox_xyxy"]
            # For small PPE items (hard hat on top of head), containment
            # is a better signal than IoU.
            score = _containment_ratio(ppe_det.bbox_xyxy, person_box)
            iou = _iou(ppe_det.bbox_xyxy, person_box)
            combined = max(score, iou)

            if combined > best_score:
                best_score = combined
                best_person = p

        if best_person is not None and best_score >= PPE_CONTAINMENT_THRESHOLD:
            best_person["ppe"][ppe_det.class_name] = True

    return persons


class VisionTracker:
    """End-to-end: frame in → tracked workers with PPE status out.

    Parameters
    ----------
    model_path : str | Path
        Path to fine-tuned YOLOv8 weights.
    confidence : float
        Passed to YOLODetector as a blanket confidence override.
        Set to None to use per-class defaults.
    track_activation_threshold : float
        ByteTrack: minimum detection confidence to initialize a track.
    lost_track_buffer : int
        Frames a track survives without a matching detection before
        being deleted.  30 frames ≈ 2 seconds at 15 FPS.
    frame_rate : int
        Expected input FPS (used by ByteTrack for velocity estimation).
    device : str
        YOLO inference device.
    """

    def __init__(
        self,
        model_path: str | Path = "models/yolov8_ppe.pt",
        confidence: float | None = None,
        track_activation_threshold: float = 0.25,
        lost_track_buffer: int = 30,
        minimum_matching_threshold: float = 0.8,
        frame_rate: int = 15,
        device: str = "cpu",
    ) -> None:
        self.detector = YOLODetector(model_path, device=device)
        self.confidence = confidence
        self.frame_rate = frame_rate
        self._tracker = None  # lazy
        self._tracker_config = {
            "track_activation_threshold": track_activation_threshold,
            "lost_track_buffer": lost_track_buffer,
            "minimum_matching_threshold": minimum_matching_threshold,
            "frame_rate": frame_rate,
        }
        self._frame_count = 0
        # track_id -> worker_id mapping (auto-assigned)
        self._track_to_worker: dict[int, str] = {}
        self._next_worker_num = 1

    def _ensure_tracker(self):
        if self._tracker is not None:
            return self._tracker
        try:
            import supervision as sv
        except ImportError as exc:
            raise ImportError(
                "supervision is required: pip install supervision"
            ) from exc

        self._tracker = sv.ByteTrack(**self._tracker_config)
        return self._tracker

    def _get_worker_id(self, track_id: int) -> str:
        """Auto-assign a W-XXX worker ID to each unique track."""
        if track_id not in self._track_to_worker:
            self._track_to_worker[track_id] = f"W-{self._next_worker_num:03d}"
            self._next_worker_num += 1
        return self._track_to_worker[track_id]

    def process_frame(
        self,
        frame: np.ndarray,
        camera_id: str = "CAM-01",
        zone_id: str = "zone-1",
    ) -> list[TrackedWorker]:
        """Process one frame and return tracked workers with PPE status.

        Returns
        -------
        List of TrackedWorker, one per tracked person in the frame.
        Empty list if no persons detected.
        """
        tracker = self._ensure_tracker()
        import supervision as sv

        # Step 1: Detect all objects (persons + PPE items)
        det_result = self.detector.detect(frame, conf_override=self.confidence)
        self._frame_count += 1

        if not det_result.detections:
            return []

        # Step 2: Split into persons and PPE items
        person_dets = det_result.persons
        ppe_dets = det_result.ppe_items

        if not person_dets:
            return []

        # Step 3: Track persons only (PPE items are associated, not tracked)
        person_xyxy = np.array([d.bbox_xyxy for d in person_dets], dtype=np.float32)
        person_conf = np.array([d.confidence for d in person_dets], dtype=np.float32)
        person_cls = np.array([d.class_id for d in person_dets], dtype=int)

        sv_detections = sv.Detections(
            xyxy=person_xyxy,
            confidence=person_conf,
            class_id=person_cls,
        )

        tracked = tracker.update_with_detections(sv_detections)

        if len(tracked) == 0:
            return []

        # Step 4: Build person records with track IDs
        persons = []
        for i in range(len(tracked)):
            track_id = int(tracked.tracker_id[i]) if tracked.tracker_id is not None else i
            persons.append({
                "track_id": track_id,
                "bbox_xyxy": tuple(tracked.xyxy[i].tolist()),
                "confidence": float(tracked.confidence[i]) if tracked.confidence is not None else 0.5,
            })

        # Step 5: Associate PPE items with persons
        persons = _associate_ppe(persons, ppe_dets)

        # Step 6: Convert to TrackedWorker objects
        workers = []
        for p in persons:
            workers.append(TrackedWorker(
                track_id=p["track_id"],
                worker_id=self._get_worker_id(p["track_id"]),
                zone_id=zone_id,
                camera_id=camera_id,
                bbox_xyxy=p["bbox_xyxy"],
                confidence=p["confidence"],
                ppe=p["ppe"],
                frame_index=self._frame_count,
            ))

        return workers

    def reset(self) -> None:
        """Reset tracker state (e.g. on camera switch)."""
        self._tracker = None
        self._frame_count = 0
        # intentionally keep _track_to_worker across resets
        # so worker IDs remain stable across short outages

    @property
    def active_track_count(self) -> int:
        if self._tracker is None:
            return 0
        # supervision's ByteTrack doesn't expose this directly;
        # return our mapping size as a proxy
        return len(self._track_to_worker)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Smoke test with synthetic frames
    tracker = VisionTracker("yolov8n.pt", device="cpu")
    for i in range(5):
        dummy = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        workers = tracker.process_frame(dummy, camera_id="CAM-01", zone_id="zone-1")
        print(f"Frame {i}: {len(workers)} workers tracked")
        for w in workers:
            print(f"  {w.worker_id}: compliant={w.is_compliant} ppe={w.ppe}")

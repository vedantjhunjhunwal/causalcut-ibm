"""Vision inference pipeline — converts tracked workers to canonical events.

Takes the output of VisionTracker (TrackedWorker objects per frame) and
produces SafetyEventIn-compatible dicts for ingestion into Vedant's API.

Two event types are emitted:
  - ``worker_presence``: worker detected in a zone with full PPE
  - ``ppe_violation``:   worker detected with missing PPE items

Debouncing: the same worker in the same zone with the same PPE state
does NOT produce duplicate events within the validity window (default
5 minutes).  A *change* in PPE state always produces a new event.

Usage:
    pipeline = VisionInferencePipeline("models/yolov8_ppe.pt")
    events = pipeline.process_frame(frame, camera_id="CAM-01", zone_id="zone-1")
    for event in events:
        httpx.post("/api/v1/events/ingest", json=event)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from src.inference.vision_tracker import TrackedWorker, VisionTracker

logger = logging.getLogger(__name__)

MODEL_VERSION = "yolov8n-ppe-v1.0.0"
PROVENANCE = "HardHatWorkers_Roboflow"
SOURCE = "ppe_detection_module"

# Debounce: don't emit duplicate events for the same worker+zone+ppe_state
# within this window.
DEBOUNCE_WINDOW = timedelta(minutes=5)


def _ppe_state_key(ppe: dict[str, bool | None]) -> str:
    """Deterministic string key for PPE state comparison."""
    return "|".join(f"{k}={v}" for k, v in sorted(ppe.items()))


class VisionInferencePipeline:
    """End-to-end: frame → canonical safety events.

    Parameters
    ----------
    model_path : str
        Path to YOLOv8 weights.
    device : str
        Inference device.
    debounce : bool
        If True (default), suppress duplicate events for the same
        worker in the same state within the debounce window.
    """

    def __init__(
        self,
        model_path: str = "models/yolov8_ppe.pt",
        device: str = "cpu",
        debounce: bool = True,
    ) -> None:
        self.tracker = VisionTracker(model_path=model_path, device=device)
        self.debounce = debounce

        # Debounce state: worker_id -> (zone_id, ppe_state_key, last_event_time)
        self._last_emitted: dict[str, tuple[str, str, datetime]] = {}

    def _should_emit(self, worker: TrackedWorker, now: datetime) -> bool:
        """Returns False if this worker's state was already emitted recently."""
        if not self.debounce:
            return True

        key = worker.worker_id
        ppe_key = _ppe_state_key(worker.ppe)

        prev = self._last_emitted.get(key)
        if prev is None:
            return True

        prev_zone, prev_ppe, prev_time = prev
        # Emit if zone changed, PPE state changed, or debounce window expired
        if prev_zone != worker.zone_id:
            return True
        if prev_ppe != ppe_key:
            return True
        if now - prev_time > DEBOUNCE_WINDOW:
            return True

        return False

    def _mark_emitted(self, worker: TrackedWorker, now: datetime) -> None:
        self._last_emitted[worker.worker_id] = (
            worker.zone_id,
            _ppe_state_key(worker.ppe),
            now,
        )

    def _worker_to_event(self, worker: TrackedWorker) -> dict[str, Any]:
        """Convert a TrackedWorker to a canonical SafetyEventIn dict."""
        now = datetime.now(timezone.utc)
        event_time = now.isoformat().replace("+00:00", "Z")

        # Determine event type
        if worker.is_compliant:
            event_type = "worker_presence"
        else:
            event_type = "ppe_violation"

        # Build value payload
        value: dict[str, Any] = {
            "camera_id": worker.camera_id,
            "present": True,
            "ppe": {k: v for k, v in worker.ppe.items()},
        }

        if not worker.is_compliant:
            value["missing"] = worker.missing_ppe

        event = {
            "event_id": str(uuid.uuid4()),
            "zone_id": worker.zone_id,
            "event_type": event_type,
            "event_time": event_time,
            "worker_id": worker.worker_id,
            "value": value,
            "severity": 0.0 if worker.is_compliant else 0.62,
            "confidence": round(worker.confidence, 4),
            "uncertainty": round(1.0 - worker.confidence, 4),
            "source": SOURCE,
            "model_version": MODEL_VERSION,
            "provenance": PROVENANCE,
            "information_class": "M",
            "synthetic_flag": False,
        }

        return event

    def process_frame(
        self,
        frame: np.ndarray,
        camera_id: str = "CAM-01",
        zone_id: str = "zone-1",
    ) -> list[dict[str, Any]]:
        """Process a single frame and return canonical events.

        Returns an empty list if no new events need to be emitted
        (either no workers detected, or all workers debounced).
        """
        now = datetime.now(timezone.utc)
        workers = self.tracker.process_frame(frame, camera_id=camera_id, zone_id=zone_id)

        events = []
        for worker in workers:
            if self._should_emit(worker, now):
                event = self._worker_to_event(worker)
                events.append(event)
                self._mark_emitted(worker, now)
                logger.debug(
                    "Emitting %s event for %s in %s",
                    event["event_type"], worker.worker_id, worker.zone_id,
                )

        return events

    def process_tracked_workers(
        self,
        workers: list[TrackedWorker],
    ) -> list[dict[str, Any]]:
        """Convert pre-tracked workers to events (for testing/simulation).

        Skips the YOLO + ByteTrack step; useful when you already have
        TrackedWorker objects from a mock or a different detector.
        """
        now = datetime.now(timezone.utc)
        events = []
        for worker in workers:
            if self._should_emit(worker, now):
                event = self._worker_to_event(worker)
                events.append(event)
                self._mark_emitted(worker, now)
        return events

    def reset_debounce(self) -> None:
        """Clear debounce state (e.g. on shift change)."""
        self._last_emitted.clear()

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "active_tracks": self.tracker.active_track_count,
            "debounced_workers": len(self._last_emitted),
            "model_version": MODEL_VERSION,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    pipeline = VisionInferencePipeline("yolov8n.pt", device="cpu")

    # Simulate 5 frames
    for i in range(5):
        dummy = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        events = pipeline.process_frame(dummy, camera_id="CAM-01", zone_id="zone-1")
        print(f"Frame {i}: {len(events)} events emitted")
        for e in events:
            print(f"  {e['event_type']}: {e['worker_id']} ppe={e['value']['ppe']}")

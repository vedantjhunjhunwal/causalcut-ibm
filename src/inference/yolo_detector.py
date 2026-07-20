"""YOLOv8-nano PPE detection wrapper.

Wraps Ultralytics YOLOv8 into a clean interface that the rest of
CAUSALCUT's inference pipeline can call without knowing anything about
the model internals.  Returns structured detections with class names
mapped to the PPE vocabulary from app/schemas/enums.py.

Usage:
    detector = YOLODetector("models/yolov8_ppe.pt")
    detections = detector.detect(frame)
    # -> [Detection(class_name="hard_hat", confidence=0.91, bbox=...), ...]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Class mapping — YOLO integer class IDs to CAUSALCUT PPE vocabulary.
# Updated after training; these defaults match the Hard-Hat Workers dataset
# from Roboflow (3 classes).
# ---------------------------------------------------------------------------
DEFAULT_CLASS_MAP: dict[int, str] = {
    0: "hard_hat",
    1: "person",
    2: "safety_vest",
}

# Confidence floors per class.  PPE items need a lower floor because
# they're small objects and the model struggles with them at distance;
# "person" can afford to be pickier so we don't hallucinate workers.
DEFAULT_CONFIDENCE_THRESHOLDS: dict[str, float] = {
    "person": 0.50,
    "hard_hat": 0.35,
    "safety_vest": 0.35,
}

FALLBACK_CONFIDENCE = 0.40


@dataclass(frozen=True)
class Detection:
    """One detected object in a single frame."""

    class_name: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]  # (x1, y1, x2, y2) absolute px
    class_id: int = -1
    # track_id is populated downstream by VisionTracker, not here.
    track_id: int | None = None

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox_xyxy
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_name": self.class_name,
            "confidence": round(self.confidence, 4),
            "bbox_xyxy": [round(v, 1) for v in self.bbox_xyxy],
            "class_id": self.class_id,
            "track_id": self.track_id,
        }


@dataclass
class DetectionResult:
    """Batch of detections from a single frame."""

    detections: list[Detection] = field(default_factory=list)
    frame_shape: tuple[int, ...] = (0, 0, 0)
    inference_ms: float = 0.0

    @property
    def persons(self) -> list[Detection]:
        return [d for d in self.detections if d.class_name == "person"]

    @property
    def ppe_items(self) -> list[Detection]:
        return [d for d in self.detections if d.class_name != "person"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "detections": [d.to_dict() for d in self.detections],
            "frame_shape": list(self.frame_shape),
            "inference_ms": round(self.inference_ms, 2),
            "person_count": len(self.persons),
            "ppe_item_count": len(self.ppe_items),
        }


class YOLODetector:
    """Thin wrapper around ultralytics.YOLO for PPE detection.

    Parameters
    ----------
    model_path : str | Path
        Path to a .pt weights file.  Accepts ``"yolov8n.pt"`` for the
        stock pretrained model (auto-downloaded by ultralytics).
    class_map : dict[int, str] | None
        Override the integer-to-name mapping.
    confidence_thresholds : dict[str, float] | None
        Per-class confidence floor.  Detections below this are dropped.
    device : str
        ``"cpu"``, ``"mps"`` (Apple Silicon), or ``"0"`` (CUDA GPU 0).
    imgsz : int
        Inference resolution.  640 is the YOLO default and a good
        speed/accuracy tradeoff on nano.
    """

    def __init__(
        self,
        model_path: str | Path = "yolov8n.pt",
        class_map: dict[int, str] | None = None,
        confidence_thresholds: dict[str, float] | None = None,
        device: str = "cpu",
        imgsz: int = 640,
    ) -> None:
        self.model_path = str(model_path)
        self.class_map = class_map or dict(DEFAULT_CLASS_MAP)
        self.thresholds = confidence_thresholds or dict(DEFAULT_CONFIDENCE_THRESHOLDS)
        self.device = device
        self.imgsz = imgsz
        self._model = None  # lazy-loaded

    # ------------------------------------------------------------------ #
    # Lazy model loading
    # ------------------------------------------------------------------ #
    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ImportError(
                "ultralytics is required: pip install ultralytics"
            ) from exc

        logger.info("Loading YOLO model from %s (device=%s)", self.model_path, self.device)
        self._model = YOLO(self.model_path)
        return self._model

    # ------------------------------------------------------------------ #
    # Core detection
    # ------------------------------------------------------------------ #
    def detect(
        self,
        frame: np.ndarray,
        conf_override: float | None = None,
    ) -> DetectionResult:
        """Run inference on a single frame.

        Parameters
        ----------
        frame : np.ndarray
            BGR or RGB image as HxWxC uint8 array.
        conf_override : float | None
            If set, use this as a blanket confidence floor instead of
            the per-class thresholds.

        Returns
        -------
        DetectionResult with all detections above their class threshold.
        """
        model = self._ensure_model()

        # ultralytics accepts numpy arrays directly; set a low floor
        # here and do per-class filtering ourselves below.
        raw_conf = 0.15
        results = model.predict(
            source=frame,
            conf=raw_conf,
            device=self.device,
            imgsz=self.imgsz,
            verbose=False,
        )

        detections: list[Detection] = []
        inference_ms = 0.0

        if results and len(results) > 0:
            r = results[0]
            inference_ms = sum(r.speed.values()) if hasattr(r, "speed") else 0.0
            boxes = r.boxes

            if boxes is not None and len(boxes) > 0:
                for i in range(len(boxes)):
                    cls_id = int(boxes.cls[i].item())
                    conf = float(boxes.conf[i].item())
                    xyxy = boxes.xyxy[i].cpu().numpy().tolist()

                    class_name = self.class_map.get(cls_id, f"class_{cls_id}")

                    # Per-class confidence gating
                    if conf_override is not None:
                        threshold = conf_override
                    else:
                        threshold = self.thresholds.get(class_name, FALLBACK_CONFIDENCE)

                    if conf < threshold:
                        continue

                    detections.append(Detection(
                        class_name=class_name,
                        confidence=conf,
                        bbox_xyxy=tuple(xyxy),
                        class_id=cls_id,
                    ))

        return DetectionResult(
            detections=detections,
            frame_shape=frame.shape if isinstance(frame, np.ndarray) else (0, 0, 0),
            inference_ms=inference_ms,
        )

    def detect_batch(
        self,
        frames: Sequence[np.ndarray],
        conf_override: float | None = None,
    ) -> list[DetectionResult]:
        """Run detection on multiple frames. Currently sequential;
        swap to batched predict if throughput needs it."""
        return [self.detect(f, conf_override=conf_override) for f in frames]

    # ------------------------------------------------------------------ #
    # Training helper (reference — actual training is a separate step)
    # ------------------------------------------------------------------ #
    @staticmethod
    def train(
        data_yaml: str,
        epochs: int = 50,
        imgsz: int = 640,
        batch: int = 16,
        device: str = "mps",
        project: str = "runs/train",
        name: str = "yolov8_ppe_v1",
    ) -> Path:
        """Fine-tune YOLOv8-nano on a PPE dataset.

        Returns the path to the best weights file.
        """
        from ultralytics import YOLO

        model = YOLO("yolov8n.pt")
        results = model.train(
            data=data_yaml,
            epochs=epochs,
            imgsz=imgsz,
            batch=batch,
            device=device,
            project=project,
            name=name,
        )
        best_path = Path(project) / name / "weights" / "best.pt"
        logger.info("Training complete. Best weights: %s", best_path)
        return best_path


if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.INFO)

    # Quick smoke test with a synthetic frame
    detector = YOLODetector("yolov8n.pt", device="cpu")

    # Generate a dummy 640x480 frame (random noise — won't detect much,
    # but proves the pipeline doesn't crash)
    dummy = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    t0 = time.perf_counter()
    result = detector.detect(dummy)
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"Detections: {len(result.detections)} | Inference: {elapsed:.1f}ms")
    for d in result.detections:
        print(f"  {d.class_name}: {d.confidence:.2f} @ {d.bbox_xyxy}")

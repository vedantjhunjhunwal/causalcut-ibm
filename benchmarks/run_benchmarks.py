"""Inference latency benchmarks.

Measures per-frame and batch processing times for:
  1. YOLOv8-nano detection
  2. YOLOv8-nano + ByteTrack tracking
  3. XGBoost gas classification
  4. IsoForest anomaly detection
  5. Multi-camera throughput estimation

Run:
    python benchmarks/run_benchmarks.py

Outputs results to benchmarks/inference_latency_report.md
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

# Add project root to path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_XGB_PATH = _ROOT / ".models" / "XGB Classifier" / "model_1&2.joblib"
_ISO_PATH = _ROOT / ".models" / "Isolation Forest Anomaly Detector" / "gas_sensor_isoforest_pipeline.joblib"


def _percentile(times: list[float], p: int) -> float:
    return float(np.percentile(times, p))


def benchmark_gas_inference(n_samples: int = 500) -> dict:
    """Benchmark XGBoost + IsoForest inference."""
    if not _XGB_PATH.exists():
        return {"skipped": True, "reason": "XGB model not found"}

    try:
        from src.inference.gas_inference import GasInferencePipeline

        pipeline = GasInferencePipeline(
            xgb_model_path=str(_XGB_PATH),
            isoforest_model_path=str(_ISO_PATH),
        )

        # Warm up
        dummy = np.random.randn(128)
        pipeline.infer(dummy)
    except Exception as exc:
        return {"skipped": True, "reason": f"Failed to load or initialize gas pipeline: {exc}"}

    # Single-sample benchmark
    times = []
    for _ in range(n_samples):
        features = np.random.randn(128)
        t0 = time.perf_counter()
        pipeline.infer(features)
        times.append((time.perf_counter() - t0) * 1000)

    # Batch benchmark
    batch_sizes = [100, 500]
    batch_results = {}
    for bs in batch_sizes:
        matrix = np.random.randn(bs, 128)
        t0 = time.perf_counter()
        pipeline.infer_batch(matrix)
        elapsed = (time.perf_counter() - t0) * 1000
        batch_results[bs] = {
            "total_ms": round(elapsed, 2),
            "per_sample_ms": round(elapsed / bs, 4),
        }

    return {
        "single_sample": {
            "n": n_samples,
            "p50_ms": round(_percentile(times, 50), 4),
            "p95_ms": round(_percentile(times, 95), 4),
            "p99_ms": round(_percentile(times, 99), 4),
            "mean_ms": round(sum(times) / len(times), 4),
            "throughput_per_sec": round(1000 / (sum(times) / len(times)), 1),
        },
        "batch": batch_results,
    }


def benchmark_yolo_detection(n_frames: int = 50) -> dict:
    """Benchmark YOLOv8-nano frame processing."""
    try:
        from src.inference.yolo_detector import YOLODetector
        detector = YOLODetector("yolov8n.pt", device="cpu")
        detector._ensure_model()  # force load
    except Exception as exc:
        return {"skipped": True, "reason": str(exc)}

    results = {}
    for res_name, (h, w) in [("640x480", (480, 640)), ("1280x720", (720, 1280))]:
        frame = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)

        # Warm up
        detector.detect(frame)

        times = []
        for _ in range(n_frames):
            t0 = time.perf_counter()
            detector.detect(frame)
            times.append((time.perf_counter() - t0) * 1000)

        results[res_name] = {
            "n_frames": n_frames,
            "p50_ms": round(_percentile(times, 50), 2),
            "p95_ms": round(_percentile(times, 95), 2),
            "p99_ms": round(_percentile(times, 99), 2),
            "fps": round(1000 / (sum(times) / len(times)), 1),
        }

    return results


def benchmark_tracking(n_frames: int = 50) -> dict:
    """Benchmark YOLOv8-nano + ByteTrack combined."""
    try:
        from src.inference.vision_tracker import VisionTracker
        tracker = VisionTracker("yolov8n.pt", device="cpu")
    except Exception as exc:
        return {"skipped": True, "reason": str(exc)}

    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

    # Warm up
    tracker.process_frame(frame)

    times = []
    for _ in range(n_frames):
        t0 = time.perf_counter()
        tracker.process_frame(frame, camera_id="CAM-01", zone_id="zone-1")
        times.append((time.perf_counter() - t0) * 1000)

    return {
        "resolution": "640x480",
        "n_frames": n_frames,
        "p50_ms": round(_percentile(times, 50), 2),
        "p95_ms": round(_percentile(times, 95), 2),
        "p99_ms": round(_percentile(times, 99), 2),
        "fps": round(1000 / (sum(times) / len(times)), 1),
    }


def estimate_multi_camera(single_frame_ms: float, target_fps: int = 15) -> dict:
    """Estimate max camera count given single-frame latency."""
    budget_ms = 1000 / target_fps  # ms per frame at target FPS
    max_cameras = int(budget_ms / single_frame_ms) if single_frame_ms > 0 else 0

    return {
        "target_fps": target_fps,
        "single_frame_ms": round(single_frame_ms, 2),
        "frame_budget_ms": round(budget_ms, 2),
        "max_cameras_sequential": max_cameras,
        "note": "With async/threaded processing, effective count is higher",
    }


def generate_report(gas: dict, yolo: dict, tracking: dict, multi_cam: dict) -> str:
    """Generate markdown benchmark report."""
    lines = [
        "# Inference Latency Benchmark Report",
        "",
        f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**System**: {os.uname().sysname} {os.uname().machine}",
        "",
        "---",
        "",
        "## Gas Inference (XGBoost + IsoForest)",
        "",
    ]

    if gas.get("skipped"):
        lines.append(f"> Skipped: {gas['reason']}")
    else:
        s = gas["single_sample"]
        lines.extend([
            "### Single-Sample Latency",
            "",
            f"| Metric | Value |",
            f"|---|---|",
            f"| Samples | {s['n']} |",
            f"| p50 | {s['p50_ms']} ms |",
            f"| p95 | {s['p95_ms']} ms |",
            f"| p99 | {s['p99_ms']} ms |",
            f"| Mean | {s['mean_ms']} ms |",
            f"| Throughput | {s['throughput_per_sec']} samples/sec |",
            "",
            "### Batch Latency",
            "",
            "| Batch Size | Total (ms) | Per Sample (ms) |",
            "|---|---|---|",
        ])
        for bs, br in gas["batch"].items():
            lines.append(f"| {bs} | {br['total_ms']} | {br['per_sample_ms']} |")

    lines.extend(["", "---", "", "## YOLO Detection (YOLOv8-nano)", ""])

    if yolo.get("skipped"):
        lines.append(f"> Skipped: {yolo['reason']}")
    else:
        lines.extend([
            "| Resolution | Frames | p50 (ms) | p95 (ms) | p99 (ms) | FPS |",
            "|---|---|---|---|---|---|",
        ])
        for res, data in yolo.items():
            if isinstance(data, dict) and "p50_ms" in data:
                lines.append(
                    f"| {res} | {data['n_frames']} | {data['p50_ms']} | "
                    f"{data['p95_ms']} | {data['p99_ms']} | {data['fps']} |"
                )

    lines.extend(["", "---", "", "## YOLO + ByteTrack Tracking", ""])

    if tracking.get("skipped"):
        lines.append(f"> Skipped: {tracking['reason']}")
    else:
        lines.extend([
            f"| Metric | Value |",
            f"|---|---|",
            f"| Resolution | {tracking['resolution']} |",
            f"| Frames | {tracking['n_frames']} |",
            f"| p50 | {tracking['p50_ms']} ms |",
            f"| p95 | {tracking['p95_ms']} ms |",
            f"| p99 | {tracking['p99_ms']} ms |",
            f"| FPS | {tracking['fps']} |",
        ])

    lines.extend(["", "---", "", "## Multi-Camera Throughput Estimate", ""])
    lines.extend([
        f"| Metric | Value |",
        f"|---|---|",
        f"| Target FPS | {multi_cam['target_fps']} |",
        f"| Single Frame | {multi_cam['single_frame_ms']} ms |",
        f"| Frame Budget | {multi_cam['frame_budget_ms']} ms |",
        f"| Max Cameras (sequential) | {multi_cam['max_cameras_sequential']} |",
        "",
        f"> {multi_cam['note']}",
    ])

    return "\n".join(lines) + "\n"


def main():
    print("=" * 60)
    print("CAUSALCUT Inference Latency Benchmarks")
    print("=" * 60)

    print("\n[1/4] Benchmarking gas inference...")
    gas = benchmark_gas_inference(500)

    print("[2/4] Benchmarking YOLO detection...")
    yolo = benchmark_yolo_detection(30)

    print("[3/4] Benchmarking YOLO + ByteTrack tracking...")
    tracking = benchmark_tracking(30)

    # Estimate multi-camera throughput
    if not tracking.get("skipped"):
        single_ms = tracking["p50_ms"]
    elif not yolo.get("skipped"):
        first_res = next(iter(yolo.values()))
        single_ms = first_res["p50_ms"] if isinstance(first_res, dict) else 100
    else:
        single_ms = 100  # fallback

    print("[4/4] Estimating multi-camera throughput...")
    multi_cam = estimate_multi_camera(single_ms)

    # Generate report
    report = generate_report(gas, yolo, tracking, multi_cam)
    report_path = _ROOT / "benchmarks" / "inference_latency_report.md"
    report_path.write_text(report)
    print(f"\nReport saved to: {report_path}")
    print(report)


if __name__ == "__main__":
    main()

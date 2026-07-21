"""Simulated edge sensor + camera streams for end-to-end testing.

Two independent streams:

  1. **Gas Telemetry Replay** — reads the UCI gas sensor CSV row by row,
     runs each through GasInferencePipeline, and POSTs the resulting
     canonical events to the ingestion API.

  2. **Worker Trajectory Simulator** — replays predefined worker movement
     paths (zone transitions + PPE state changes) as vision events.

Both streams can run together or independently, at real-time or
accelerated speed.

Usage:
    # Replay 200 gas rows + 5 workers at 60× real-time speed
    python src/simulator/mock_edge_stream.py \\
        --url http://localhost:8000 \\
        --mode both \\
        --speed 60 \\
        --gas-rows 200 \\
        --workers 5

    # Gas only, first 50 rows, real-time
    python src/simulator/mock_edge_stream.py --mode gas --gas-rows 50 --speed 1
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np

logger = logging.getLogger(__name__)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# -----------------------------------------------------------------------
# Sensor-to-zone mapping (design doc §2.1)
# -----------------------------------------------------------------------
SENSOR_ZONE_MAP: dict[str, str] = {
    **{f"GS-{i:02d}": "zone-1" for i in range(1, 9)},
    **{f"GS-{i:02d}": "zone-2" for i in range(9, 17)},
}

# -----------------------------------------------------------------------
# Worker trajectory definitions
# -----------------------------------------------------------------------
# Each trajectory is a list of (elapsed_seconds, zone_id, ppe_state).
# The simulator walks through these at the configured speed multiplier.
WORKER_TRAJECTORIES: list[dict[str, Any]] = [
    {
        "worker_id": "W-001",
        "path": [
            (0, "zone-5", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (30, "zone-1", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (180, "zone-1", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (300, "zone-5", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
        ],
    },
    {
        "worker_id": "W-002",
        "path": [
            (0, "zone-5", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (20, "zone-2", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (200, "zone-2", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (350, "zone-5", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
        ],
    },
    {
        "worker_id": "W-003",
        "path": [
            (0, "zone-5", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (60, "zone-1", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (240, "zone-1", {"hard_hat": False, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (300, "zone-1", {"hard_hat": False, "safety_vest": False, "safety_goggles": None, "gloves": None}),
            (360, "zone-5", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
        ],
    },
    {
        "worker_id": "W-004",
        "path": [
            (0, "zone-5", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (45, "zone-3", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (250, "zone-3", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (400, "zone-5", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
        ],
    },
    {
        "worker_id": "W-005",
        "path": [
            (0, "zone-5", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (40, "zone-1", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (150, "zone-4", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
            (280, "zone-2", {"hard_hat": True, "safety_vest": False, "safety_goggles": None, "gloves": None}),
            (370, "zone-5", {"hard_hat": True, "safety_vest": True, "safety_goggles": None, "gloves": None}),
        ],
    },
]


def _build_worker_event(
    worker_id: str,
    zone_id: str,
    ppe: dict[str, bool | None],
    camera_id: str = "CAM-01",
) -> dict[str, Any]:
    """Build a canonical event dict for a worker presence/violation."""
    missing = [k for k, v in ppe.items() if v is False]
    event_type = "ppe_violation" if missing else "worker_presence"

    event = {
        "event_id": str(uuid.uuid4()),
        "zone_id": zone_id,
        "event_type": event_type,
        "event_time": _iso(datetime.now(timezone.utc)),
        "worker_id": worker_id,
        "value": {
            "camera_id": camera_id,
            "present": True,
            "ppe": {k: v for k, v in ppe.items()},
        },
        "severity": 0.62 if missing else 0.0,
        "confidence": round(0.90 + random.uniform(0, 0.08), 4),
        "source": "ppe_detection_module",
        "model_version": "yolov8n-ppe-v1.0.0",
        "provenance": "mock_edge_stream",
        "information_class": "M",
        "synthetic_flag": False,
    }

    if missing:
        event["value"]["missing"] = missing

    return event


# -----------------------------------------------------------------------
# Gas telemetry stream
# -----------------------------------------------------------------------
async def run_gas_stream(
    client: httpx.AsyncClient,
    csv_path: Path,
    max_rows: int,
    speed: float,
    interval_seconds: float = 5.0,
) -> dict[str, int]:
    """Replay gas sensor CSV through the inference pipeline."""
    import pandas as pd

    # Lazy import — don't fail if models aren't available
    from src.inference.gas_inference import GasInferencePipeline

    df = pd.read_csv(csv_path, nrows=max_rows)
    feature_cols = [c for c in df.columns if c not in ("label", "source_file")]
    X = df[feature_cols].values
    labels = df["label"].values if "label" in df.columns else [None] * len(df)
    batches = df["source_file"].values if "source_file" in df.columns else ["unknown"] * len(df)

    pipeline = GasInferencePipeline()
    stats = {"sent": 0, "accepted": 0, "rejected": 0, "errors": 0}

    print(f"\n[GAS] Replaying {len(X)} sensor readings at {speed}× speed\n")

    for i, row in enumerate(X):
        sensor_id = f"GS-{(i % 16) + 1:02d}"
        zone_id = SENSOR_ZONE_MAP.get(sensor_id, "zone-1")
        batch_id = str(batches[i]) if batches[i] is not None else None

        event = pipeline.infer(row, sensor_id=sensor_id, zone_id=zone_id, batch_id=batch_id)

        try:
            r = await client.post("/api/v1/events/ingest", json=event)
            body = r.json()
            status = body.get("results", [{}])[0].get("status", "unknown")
            stats["sent"] += 1

            if status == "accepted":
                stats["accepted"] += 1
            elif status == "rejected":
                stats["rejected"] += 1

            gas = event["value"]["gas_type"]
            drift = "DRIFT" if event["value"]["drift_detected"] else "ok"
            print(
                f"  [{i:>4}] {sensor_id} {zone_id}  gas={gas:<14} "
                f"sev={event['severity']:<5}  drift={drift:<5}  → {status}"
            )
        except Exception as exc:
            stats["errors"] += 1
            logger.warning("Gas event %d failed: %s", i, exc)

        # Pacing
        delay = interval_seconds / speed
        if delay > 0:
            await asyncio.sleep(delay)

    return stats


# -----------------------------------------------------------------------
# Worker trajectory stream
# -----------------------------------------------------------------------
async def run_worker_stream(
    client: httpx.AsyncClient,
    num_workers: int,
    speed: float,
) -> dict[str, int]:
    """Replay worker trajectories as vision events."""
    trajectories = WORKER_TRAJECTORIES[:num_workers]
    stats = {"sent": 0, "accepted": 0, "violations": 0, "errors": 0}

    # Flatten all waypoints into a time-sorted sequence
    waypoints: list[tuple[float, str, str, dict]] = []
    for traj in trajectories:
        for elapsed, zone_id, ppe in traj["path"]:
            waypoints.append((elapsed, traj["worker_id"], zone_id, ppe))

    waypoints.sort(key=lambda w: w[0])

    print(f"\n[VISION] Replaying {len(waypoints)} worker waypoints at {speed}× speed\n")

    prev_time = 0.0
    for elapsed, worker_id, zone_id, ppe in waypoints:
        delay = (elapsed - prev_time) / speed
        if delay > 0:
            await asyncio.sleep(delay)
        prev_time = elapsed

        camera_map = {
            "zone-1": "CAM-01", "zone-2": "CAM-03", "zone-3": "CAM-05",
            "zone-4": "CAM-07", "zone-5": "CAM-09", "zone-6": "CAM-10",
        }
        camera_id = camera_map.get(zone_id, "CAM-01")

        event = _build_worker_event(worker_id, zone_id, ppe, camera_id)

        try:
            r = await client.post("/api/v1/events/ingest", json=event)
            body = r.json()
            status = body.get("results", [{}])[0].get("status", "unknown")
            stats["sent"] += 1
            if status == "accepted":
                stats["accepted"] += 1

            is_violation = event["event_type"] == "ppe_violation"
            if is_violation:
                stats["violations"] += 1

            tag = "⚠️  PPE VIOLATION" if is_violation else "✓"
            print(
                f"  T={elapsed:>4.0f}s  {worker_id}  {zone_id}  "
                f"{tag}  → {status}"
            )
        except Exception as exc:
            stats["errors"] += 1
            logger.warning("Worker event for %s failed: %s", worker_id, exc)

    return stats


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------
async def main() -> None:
    ap = argparse.ArgumentParser(description="Mock edge sensor + camera streams")
    ap.add_argument("--url", default="http://localhost:8000", help="API base URL")
    ap.add_argument("--mode", choices=["gas", "vision", "both"], default="both")
    ap.add_argument("--speed", type=float, default=60.0, help="Real-time multiplier")
    ap.add_argument("--gas-rows", type=int, default=200, help="Max CSV rows to replay")
    ap.add_argument("--workers", type=int, default=5, help="Number of worker trajectories")
    ap.add_argument("--api-key", default=None, help="API key for auth")
    args = ap.parse_args()

    headers = {"X-Correlation-ID": f"mock-stream-{uuid.uuid4().hex[:8]}"}
    if args.api_key:
        headers["X-API-Key"] = args.api_key

    csv_path = Path(__file__).resolve().parent.parent.parent / ".datasets" / "gas_sensors_drift.csv"

    async with httpx.AsyncClient(base_url=args.url, headers=headers, timeout=15) as client:
        # Health check
        try:
            health = await client.get("/api/v1/health")
            health.raise_for_status()
            info = health.json()
            print(f"Connected: {info.get('app', '?')} v{info.get('version', '?')}")
        except Exception as exc:
            print(f"Cannot reach API at {args.url}: {exc}")
            return

        print(f"Mode: {args.mode} | Speed: {args.speed}× | Gas rows: {args.gas_rows}")
        print("=" * 65)

        tasks = []

        if args.mode in ("gas", "both"):
            if not csv_path.exists():
                print(f"[WARN] Gas CSV not found at {csv_path} — skipping gas stream")
            else:
                tasks.append(run_gas_stream(client, csv_path, args.gas_rows, args.speed))

        if args.mode in ("vision", "both"):
            tasks.append(run_worker_stream(client, args.workers, args.speed))

        results = await asyncio.gather(*tasks)

        print("\n" + "=" * 65)
        print("STREAM COMPLETE")
        for r in results:
            print(f"  {r}")

        # Final stats from the API
        try:
            stats = (await client.get("/api/v1/stats")).json()
            print(f"\nEvent store: {stats.get('events_by_information_class', {})}")
            print(f"Queue: {stats.get('queue', {})}")
        except Exception:
            pass


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    asyncio.run(main())

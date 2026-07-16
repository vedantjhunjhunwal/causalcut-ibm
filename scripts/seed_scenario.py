"""Replay the coke-oven scenario (design doc §8.1) against a running API.

Usage:
    python scripts/seed_scenario.py [--url http://localhost:8000] [--speed 60]

`--speed 60` compresses one scenario-minute into one real second, so the full
T=0:00 -> T=7:30 escalation runs in ~8 seconds. Every event is tagged exactly
as the design doc tags it — [M] measured, [P] predicted, [S] synthetic — so the
information-class separation is exercised end-to-end from day one.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

import httpx


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


T0 = datetime.now(timezone.utc)


def at(minutes: float) -> str:
    return iso(T0 + timedelta(minutes=minutes))


# (scenario_minute, event) — mirrors §8.1 beat for beat.
TIMELINE: list[tuple[float, dict]] = [
    # T = 0:00 — normal state
    (0.0, {
        "zone_id": "zone-1", "event_type": "gas_anomaly", "event_time": at(0),
        "value": {"sensor_id": "GS-03", "gas_type": "ammonia",
                  "concentration_ppm": 12.0, "unit": "ppm"},
        "severity": 0.05, "confidence": 0.97, "source": "gas_anomaly_module_v2",
        "model_version": "xgb-gas-v2.1.0", "provenance": "UCI_GasSensorDrift_Batch7",
        "information_class": "M",
    }),
    (0.0, {
        "zone_id": "zone-1", "event_type": "permit_status", "event_time": at(0),
        "value": {"permit_id": "PTW-007", "permit_type": "hot_work",
                  "status": "active", "issued_to": "W-001", "issued_by": "SO-A",
                  "valid_from": at(-240), "valid_to": at(240)},
        "severity": 0.0, "confidence": 1.0, "source": "permit_generator",
        "information_class": "S", "synthetic_flag": True,
    }),
    (0.0, {
        "zone_id": "zone-1", "event_type": "worker_presence", "event_time": at(0),
        "worker_id": "W-003",
        "value": {"camera_id": "CAM-01", "present": True,
                  "ppe": {"hard_hat": True, "safety_vest": True,
                          "safety_goggles": True, "gloves": True}},
        "confidence": 0.96, "source": "ppe_detection_module",
        "model_version": "yolov8n-ppe-v1.0.0", "provenance": "SH17_sample",
        "information_class": "M",
    }),
    (0.0, {
        "zone_id": "zone-1", "event_type": "barrier_status", "event_time": at(0),
        "value": {"barrier_id": "FS-Z1", "barrier_type": "fire_suppression",
                  "status": "active"},
        "confidence": 1.0, "source": "barrier_monitor", "information_class": "M",
    }),

    # T = 3:00 — rising gas [M]
    (3.0, {
        "zone_id": "zone-1", "event_type": "gas_anomaly", "event_time": at(3),
        "value": {"sensor_id": "GS-03", "gas_type": "ammonia",
                  "concentration_ppm": 180.0, "unit": "ppm", "trend": "rising"},
        "severity": 0.38, "confidence": 0.92, "uncertainty": 0.10,
        "source": "gas_anomaly_module_v2", "model_version": "xgb-gas-v2.1.0",
        "provenance": "UCI_GasSensorDrift_Batch7", "information_class": "M",
    }),
    (3.0, {
        "zone_id": "zone-1", "event_type": "gas_anomaly", "event_time": at(3),
        "value": {"sensor_id": "GS-07", "gas_type": "ammonia",
                  "concentration_ppm": 165.0, "unit": "ppm"},
        "severity": 0.34, "confidence": 0.90, "uncertainty": 0.10,
        "source": "gas_anomaly_module_v2", "model_version": "xgb-gas-v2.1.0",
        "information_class": "M",
    }),

    # T = 5:30 — hot work still active against rising gas [P]
    (5.5, {
        "zone_id": "zone-1", "event_type": "permit_conflict", "event_time": at(5.5),
        "value": {"permit_id": "PTW-007", "conflict": "hot_work_with_rising_gas",
                  "rule": "PTW-HOTWORK-GAS-01"},
        "severity": 0.55, "confidence": 0.88, "uncertainty": 0.12,
        "source": "permit_validation_module", "model_version": "rules-v1.0.0",
        "information_class": "P",
    }),

    # T = 6:00 — PPE violation [M]
    (6.0, {
        "zone_id": "zone-1", "event_type": "ppe_violation", "event_time": at(6),
        "worker_id": "W-003",
        "value": {"camera_id": "CAM-01", "present": True, "missing": ["hard_hat"],
                  "ppe": {"hard_hat": False, "safety_vest": True,
                          "safety_goggles": True, "gloves": True}},
        "severity": 0.62, "confidence": 0.94, "source": "ppe_detection_module",
        "model_version": "yolov8n-ppe-v1.0.0", "information_class": "M",
    }),

    # T = 7:00 — ventilation degrading [M] + forecast [P]
    (7.0, {
        "zone_id": "zone-1", "event_type": "utility_condition", "event_time": at(7),
        "value": {"sensor_id": "VENT-01", "sensor_kind": "flow", "value": 72.0,
                  "unit": "pct_nominal", "trend": "declining"},
        "severity": 0.55, "confidence": 0.95, "source": "utility_monitor",
        "information_class": "M",
    }),
    (7.0, {
        "zone_id": "zone-4", "event_type": "utility_condition", "event_time": at(7),
        "value": {"sensor_id": "PRESS-02", "sensor_kind": "pressure", "value": 2.1,
                  "unit": "bar", "anomaly": True},
        "severity": 0.48, "confidence": 0.93, "source": "utility_monitor",
        "information_class": "M",
    }),
    (7.0, {
        "zone_id": "zone-1", "event_type": "equipment_failure", "event_time": at(7),
        "asset_id": "VENT-01",
        "value": {"prediction": "flow_below_50pct", "horizon_minutes": 10,
                  "failure_probability": 0.76},
        "severity": 0.72, "confidence": 0.76, "uncertainty": 0.20,
        "source": "equipment_failure_module", "model_version": "lgbm-ai4i-v1.0.0",
        "provenance": "AI4I_2020", "information_class": "P",
    }),

    # T = 7:30 — compound hyperedge HE-042 activates
    (7.5, {
        "zone_id": "zone-1", "event_type": "gas_anomaly", "event_time": at(7.5),
        "value": {"sensor_id": "GS-03", "gas_type": "ammonia",
                  "concentration_ppm": 215.4, "unit": "ppm", "trend": "rising"},
        "severity": 0.82, "confidence": 0.91, "uncertainty": 0.15,
        "source": "gas_anomaly_module_v2", "model_version": "xgb-gas-v2.1.0",
        "provenance": "UCI_GasSensorDrift_Batch7", "information_class": "M",
    }),
    (7.5, {
        "zone_id": "zone-1", "event_type": "compound_risk", "event_time": at(7.5),
        "value": {"hyperedge_id": "HE-042",
                  "constituent_nodes": ["W-003", "zone-1", "PTW-007", "GS-03", "VENT-01"],
                  "pathway": "toxic_exposure_or_flash_fire",
                  "time_to_harm_minutes": 8.2, "time_to_harm_uncertainty": 3.1},
        "severity": 0.92, "confidence": 0.78, "uncertainty": 0.22,
        "source": "compound_risk_engine", "model_version": "hypergraph-v0.1.0",
        "information_class": "P",
    }),
]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--speed", type=float, default=60.0,
                    help="scenario-minutes per real second")
    ap.add_argument("--api-key", default=None)
    args = ap.parse_args()

    headers = {"X-Correlation-ID": "seed-coke-oven-scenario"}
    if args.api_key:
        headers["X-API-Key"] = args.api_key

    async with httpx.AsyncClient(base_url=args.url, headers=headers, timeout=10) as c:
        health = await c.get("/api/v1/health")
        health.raise_for_status()
        print(f"connected: {health.json()['app']} v{health.json()['version']}\n")

        elapsed = 0.0
        for minute, event in TIMELINE:
            delay = (minute - elapsed) * 60 / args.speed
            if delay > 0:
                await asyncio.sleep(delay)
                elapsed = minute

            # Scenario minutes are fictional; event_time must be real wall-clock
            # or the ingest clock-sanity guard will (correctly) reject it.
            payload = {**event, "event_time": iso(datetime.now(timezone.utc))}
            r = await c.post("/api/v1/events/ingest", json=payload)
            res = r.json()["results"][0]
            ic = event["information_class"]
            print(f"T={minute:>4.1f}  [{ic}] {event['event_type']:<20} "
                  f"sev={event.get('severity', 0):<5} -> {res['status']}")

        await asyncio.sleep(0.5)
        stats = (await c.get("/api/v1/stats")).json()
        print("\nby information class:", stats["events_by_information_class"])
        print("queue:", stats["queue"])

        zone = (await c.get("/api/v1/state/zones/zone-1")).json()
        print(f"\nzone-1 sensors: {len(zone['sensor_readings'])}, "
              f"workers: {len(zone['workers_present'])}, "
              f"active permits: {len(zone['active_permits'])}")
        for w in zone["workers_present"]:
            print(f"  {w['worker_id']}: ppe_compliant={w['ppe_compliant']} {w['ppe']}")


if __name__ == "__main__":
    asyncio.run(main())

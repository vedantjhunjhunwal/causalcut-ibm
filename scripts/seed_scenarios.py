#!/usr/bin/env python
"""
Seed all scenario JSON files from the scenarios/ directory into Supabase.

Run with:
    .venv\Scripts\python.exe -m scripts.seed_scenarios

This is idempotent (upsert) — safe to run multiple times.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "scenarios"


async def main() -> None:
    from app.db.session import Database
    from app.db.repositories import ScenarioRepository

    db = await Database().connect()
    repo = ScenarioRepository(db)
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    json_files = sorted(SCENARIO_DIR.glob("*.json"))
    if not json_files:
        print("No scenario JSON files found in", SCENARIO_DIR)
        return

    print(f"Found {len(json_files)} scenario file(s) to seed:\n")

    ok_count = 0
    skip_count = 0
    fail_count = 0

    for path in json_files:
        try:
            from app.schemas.scenario import Scenario
            data = json.loads(path.read_text(encoding="utf-8"))
            scenario = Scenario.model_validate(data)
        except Exception as exc:
            print(f"  [SKIP] {path.name} — Pydantic validation failed: {exc}")
            skip_count += 1
            continue

        # Ensure factory row exists (try both PK column names)
        for pk_col in ("id", "factory_id"):
            try:
                db.client.table("factories").upsert(
                    {pk_col: str(scenario.factory_id), "name": scenario.name or "Factory"},
                    on_conflict=pk_col,
                ).execute()
                break
            except Exception:
                pass

        saved = await repo.upsert_scenario(
            scenario_id=scenario.scenario_id,
            factory_id=str(scenario.factory_id),
            name=scenario.name or "",
            description=scenario.description or "",
            payload_json=json.dumps(data),
            created_at=now_iso,
        )
        if saved:
            print(f"  [OK]   {path.name} — {scenario.scenario_id}")
            ok_count += 1
        else:
            # upsert_scenario returns False for both "already exists" (idempotent)
            # AND real errors. Check if the row is actually in the DB.
            existing = await repo.list_scenarios(limit=100)
            ids = {r["scenario_id"] for r in existing}
            if scenario.scenario_id in ids:
                print(f"  [DUP]  {path.name} — already in DB ({scenario.scenario_id})")
                skip_count += 1
            else:
                print(f"  [FAIL] {path.name} — upsert failed (scenario not in DB after upsert)")
                fail_count += 1

    print(f"\nDone: {ok_count} inserted, {skip_count} skipped/already-existed, {fail_count} failed.")

    # Summary of what's in DB now
    print("\n--- Current scenarios in DB ---")
    scenarios = await repo.list_scenarios(limit=50)
    for s in scenarios:
        print(f"  {s['scenario_id']:45s}  {s['name'][:60]}")
    print(f"Total: {len(scenarios)}")

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())

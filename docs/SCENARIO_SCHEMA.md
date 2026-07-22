# CAUSALCUT Scenario Schema (v1.0.0)

One schema is shared by the **frontend builder form**, **JSON upload**, the
**backend `/scenario/*` API**, and the **scenario runner**. It is defined in
`app/schemas/scenario.py` (`Scenario`) and lowers to the canonical
`SafetyEvent` stream (`app/schemas/canonical.py`) via `Scenario.to_events()`.

Get a blank template from `GET /api/v1/scenario/template` or
`scenarios/blank_template.json`.

## Top-level fields

| field | type | notes |
|---|---|---|
| `scenario_id` | string | auto-generated if omitted (`scn-xxxxxxxx`) |
| `name` | string **(required)** | 1–120 chars |
| `description` | string | free text |
| `factory_id` | string | default `steelforge-001` |
| `base_time` | ISO datetime | anchor for event offsets; defaults to now (UTC) |
| `safety_threshold` | float 0–1 | residual-risk target the cut must reach (default `0.15`) |
| `zones` | Zone[] **(≥1 required)** | |
| `zone_adjacency` | Adjacency[] | propagation links between zones |
| `assets` | Asset[] | machines / equipment |
| `sensors` | Sensor[] | gas / airflow / etc. |
| `gas_readings` | GasReading[] | timestamped concentrations |
| `workers` | Worker[] | presence + PPE |
| `permits` | Permit[] | active work permits |
| `events` | ScenarioEvent[] | explicit timeline events |
| `metadata` | object | anything |

Referential integrity is enforced: every `zone_id` referenced by a sensor,
asset, worker, permit, adjacency link, gas reading or event must exist in
`zones`, or validation fails with a field-level error.

## Entities

**Zone** — `zone_id*`, `name`, `hazard_class`
(`standard|gas_hazard|high_risk|rotating_equipment|propagation|admin`),
`baseline_gas_threshold_ppm`, `ventilation_status`
(`nominal|degraded|failed`), `ventilation_flow_ratio` (0–1).

**Adjacency** — `zone_a*`, `zone_b*`, `medium`
(`ventilation_duct|shared_duct|utility_bus|doorway|shared_utility`). The medium
maps to a propagation weight used by the risk propagator.

**Sensor** — `sensor_id*`, `zone_id*`, `modality`, `unit`.

**Asset** — `asset_id*`, `zone_id*`, `asset_type`, `failure_probability` (0–1),
`condition`. A non-zero failure probability emits an `equipment_failure` event.

**GasReading** — `sensor_id*`, `zone_id*`, `gas_type`, `concentration_ppm*`,
`severity` (0–1), `confidence` (0–1), `offset_seconds`. Emits a
`gas_anomaly` event at `base_time + offset_seconds`.

**Worker** — `worker_id*`, `zone_id`, `present`, `missing_ppe` (list, e.g.
`["hard_hat"]`). Presence emits `worker_presence`; a non-empty `missing_ppe`
emits `ppe_violation`.

**Permit** — `permit_id*`, `zone_id*`, `permit_type`
(`hot_work|confined_space|electrical_isolation|mechanical|loto|working_at_height`),
`status` (`active|suspended|closed|expired`), `worker_id`. An active permit
emits a `permit_status` event.

**ScenarioEvent** (explicit timeline) — `event_type*`
(`gas_anomaly|ppe_violation|worker_presence|permit_status|utility_condition|equipment_failure|barrier_status`),
`zone_id*`, `offset_seconds`, `worker_id`, `asset_id`, `sensor_id`,
`permit_id`, `value` (event-type body), `severity`, `confidence`,
`information_class` (`M|P|S|C|R|H`), `label`.

## Information classes

Every generated event is tagged and never silently reclassified:
`M` measured · `P` predicted · `S` synthetic · `C` counterfactual ·
`R` regulatory · `H` human. Declarative state lowers to the appropriate class
automatically (gas → `M`, ventilation → `P`, permit → `S`).

## Lifecycle

```
POST /scenario/validate   → {valid, errors[], event_count}
POST /scenario/run        → {run_id, result{...}}   (only on explicit request)
GET  /scenario/{id}       → cached result
GET  /scenario/{id}/graph → node/edge graph payload
POST /scenario/{id}/decision (X-API-Key) → audit-persisted approve/reject
```

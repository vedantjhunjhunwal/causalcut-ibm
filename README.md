# CAUSALCUT — Day 1

*Causal Accident-path Uncovering System with Automated Least-Cut Intervention*
Steelforge Industries · Minimum-Causal-Cut Safety Twin

> "Not what went wrong — what to cut, right now, to keep everyone safe."

Day 1 builds the **spine**: the canonical event contract, the trust boundary, the
durable state store, and the async dispatch path. No models, no hypergraph, no
optimiser yet — those all plug into the queue that exists as of today.

---

## What runs today

```
producer ──► POST /api/v1/events/ingest
                │
                ▼
        ┌───────────────────┐
        │ validate + tag    │  Pydantic v2, information_class enforced
        └────────┬──────────┘
                 ▼
        ┌───────────────────┐
        │ PERSIST           │  events table, append-only, SQLite WAL
        └────────┬──────────┘
                 ▼
        ┌───────────────────┐
        │ asyncio.Queue     │  bounded, backpressure-aware
        └────────┬──────────┘
                 ▼
        ┌───────────────────┐
        │ consumer pool     │  projects → sensor_latest / worker_zones / permits
        └────────┬──────────┘   failures → dead_letter
                 ▼
          GET /api/v1/state/zones/{zone_id}
```

## Quick start

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://localhost:8000/docs
pytest tests -q                        # 26 tests
python scripts/seed_scenario.py        # replays the §8.1 coke-oven escalation
```

Or `docker compose up --build`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/events/ingest` | One canonical event → queue |
| `POST` | `/api/v1/events/ingest/batch` | Up to 500; partial success |
| `GET` | `/api/v1/events/{event_id}` | Read from the append-only store |
| `GET` | `/api/v1/events` | Recent, filterable by zone / type / info class |
| `GET` | `/api/v1/events/dead-letter/list` | What failed downstream |
| `GET` | `/api/v1/state/zones/{zone_id}` | Plant-state projection |
| `GET` | `/api/v1/state/permits` | Active permit registry |
| `GET` | `/api/v1/state/workers` | Occupancy + PPE status |
| `GET` | `/api/v1/state/sensors/{id}/history` | Rolling telemetry |
| `GET` | `/api/v1/health` · `/ready` · `/stats` | Liveness, readiness, counters |

Swagger at `/docs`, ReDoc at `/redoc`, schema at `/openapi.json`.

---

## Four decisions worth defending in review

**1. Persist before enqueue.** Most tutorials queue first and write later. We
invert it. A `202` means the event is durably in the append-only store — the
queue is only a dispatch hint. Consequence: a full queue, a crashed consumer, or
a restart costs *latency*, never *evidence*. For a system whose entire claim is
an auditable causal chain, a lost event is worse than a late one.

**2. The information class is a schema invariant, not a column.** §1.2 promises
strict separation between measured / predicted / synthetic / counterfactual /
regulatory / human. That promise is worthless if enforced by convention, so it
is enforced by validators that reject at the boundary:

- `M` + `synthetic_flag=true` → rejected. A measurement is from the plant or it isn't.
- `P` without `model_version` → rejected. A prediction that can't name its model can't be recalibrated.
- `C` with `uncertainty=0` → rejected. A counterfactual is never certain.

Later, when the optimiser explains *why* it cut a permit, every input already
carries its epistemic status. That is retrofit-proof only if it starts here.

**3. Append-only enforced by a trigger.** `events` has a `BEFORE DELETE` trigger
that aborts. Not a code review rule — a database rule. The audit trail is the
product.

**4. WAL, deliberately.** Ingest writes continuously; the console and (soon) the
hypergraph engine read continuously. Under the default rollback journal every
writer blocks every reader. Under WAL neither blocks the other. `/ready` fails
if the journal mode is anything but `wal`, so a misconfigured deploy is loud.

## Schema invariants under test

`pytest tests -q` → 26 passing, covering: class/flag contradictions, missing
`model_version` on `[P]`, zero-uncertainty `[C]`, naive timestamps, out-of-bounds
severity, unknown fields, future-clock rejection, staleness, content-hash dedup,
event immutability, ingest idempotency, batch partial success, WAL assertion,
delete-trigger enforcement, and the full ingest → queue → projection round trip.

## Layout

```
app/
  main.py                  # app factory, lifespan (db + queue + consumers)
  core/     config logging middleware exceptions
  schemas/  enums canonical ingest      # the contract
  db/       schema.sql session repositories
  queue/    event_queue consumer        # asyncio.Queue + projection
  api/      deps v1/router v1/routes/{health,events,state}
tests/test_day1.py
scripts/seed_scenario.py                # §8.1 replay
```

## Deliberate omissions (and why)

- **`risk_score` returns `null`**, not `0.0`. Risk is `[P]` and arrives with the
  hypergraph engine. A default of zero on a safety console reads as "safe."
- **No auth by default.** Set `CAUSALCUT_API_KEY` to turn on the key check on
  write paths. Real RBAC is required before the Human Approval Gateway ships —
  that endpoint changes plant state and cannot sit behind a shared secret.
- **Asset condition table deferred** to the equipment-failure module. Events are
  already durable, so nothing is lost by projecting later.

## Next

Day 2 plugs the gas-anomaly module (XGBoost on UCI Gas Sensor Array Drift) into
this queue as the first real consumer, emitting `[P]` events through the same
canonical schema. The contract doesn't change — that's the point of building it
first.

---

**Safety note.** Per §9.4, nothing here is a safety-rated control system. The
architecture never executes an intervention without human approval, and
recommendations must not be a sole decision basis without a certified
process-safety review and SIL assessment.

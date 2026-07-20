# CAUSALCUT

**Causal Accident-path Uncovering System with Automated Least-CUT Intervention**

A defensive industrial-safety "safety twin" for a steel plant. CAUSALCUT ingests
a live stream of plant events, maintains a materialised plant-state store, models
the plant as a dynamic **safety hypergraph**, detects **compound accident chains**
(condition combinations that are individually tolerable but jointly dangerous),
and computes the **minimum set of interventions** that breaks every high-risk
pathway — subject to cost, disruption, and human-approval constraints.

The system only ever *recommends*. Every intervention is gated behind an
authenticated human approval and recorded in a tamper-evident audit log.

---

## Architecture — two halves, one monolith

CAUSALCUT is a **modular monolith** (design doc Appendix B — deliberately no
Kafka / k8s / graph-DB for the MVP). It has two cooperating halves that share a
single event stream:

```
                         ┌──────────────────────── FastAPI app (app.main) ───────────────────────┐
   plant events          │                                                                        │
  ─────────────────────► │  POST /api/v1/events/ingest                                            │
                         │        │  validate → tag → PERSIST → dispatch                           │
                         │        ▼                                                                │
                         │   append-only event store (SQLite, WAL)                                 │
                         │        │                                                                │
                         │        ▼                                                                │
                         │   EventQueue ──► ConsumerPool ─────────────────────────┐                │
                         │                     │                                  │                │
   INGESTION SPINE       │                     ▼                                  ▼                │
   (schemas, DB, queue)  │           StateProjector                        RiskEngine (subscriber) │
                         │           (plant-state store)                   in-memory hypergraph    │  ANALYTICAL HALF
                         │             permits / workers /                       │                 │  (engine, gateway)
                         │             sensors / barriers                        ▼                 │
                         │                     │                        compound rules →           │
                         │                     ▼                        accident sub-pathways →     │
                         │   GET /api/v1/state/zones/{zone}             minimum causal cut          │
                         │                                                       │                 │
                         │                                     GET /api/v1/risk/recommendation      │
                         │                                     POST /api/v1/risk/approve            │
                         │                                        (auth + write-ahead audit log)    │
                         └────────────────────────────────────────────────────────────────────────┘
```

**Ingestion spine** (`app/schemas`, `app/db`, `app/queue`, `app/api`, `app/core`)
— the canonical event schema, the WAL SQLite plant-state store, the async
ingestion queue with backpressure and dead-lettering, and the HTTP boundary with
correlation-id tracing, structured logging, timeouts and body limits.

**Analytical half** (`app/engine`, `app/gateway`, `app/analysis`) — the NetworkX
safety hypergraph, the compound-rule engine, the OR-Tools minimum-causal-cut
optimiser, the shift-handover validator, and the authenticated + audited approval
gateway.

The two halves meet at exactly one seam: the `RiskEngine` subscribes to the same
events the `StateProjector` writes to SQLite, converting each canonical event to
the engine's internal domain model via `app/engine/adapter.py`. The risk engine
runs *after* the durable projection and is fully isolated — a risk-engine error
can never fail, retry, or dead-letter a correctly-projected event.

---

## What it does (one scenario)

The coke-oven escalation (design doc §8), replayable via `scripts/seed_scenario.py`
or the dashboard's "Ingest Coke-Oven Scenario" button:

| Plant time | Event | System state |
|-----------|-------|--------------|
| t=0s   | Worker W-003 in Zone-1 | below threshold |
| t=5s   | Hot-work permit PTW-007 active | below threshold |
| t=180s | Gas rising to 180 ppm (sub-critical) | below threshold |
| t=360s | W-003 missing hard-hat | below threshold — a lone PPE issue is not a flash-fire pathway |
| t=420s | Ventilation degrades to 0.55 | below threshold — still no gas source |
| t=450s | Gas hits 215 ppm (critical) | **3 accident paths activate → minimum cut computed** |

At t=450s the compound hazard materialises and CAUSALCUT recommends:

```
minimum causal cut (residual 0.098 vs threshold 0.15, cost LOW):
   1. Suspend hot-work permit PTW-007 in zone-1
   2. Evacuate worker W-003 from zone-1
```

It deliberately does **not** close the zone (the "sledgehammer"): a cheaper
two-action cut drives residual risk below the safety threshold, so the weighted
optimiser prefers it.

---

## Running it

### Local (no Docker)

```bash
pip install -r requirements.txt

# full test suite (50 tests: ingestion spine + engine + integration)
pytest tests -q          # or:  make test

# start the API
make run                 # uvicorn app.main:app --reload  → http://localhost:8000
```

With the server running, replay the scenario in another terminal:

```bash
make seed                # python scripts/seed_scenario.py --speed 60
```

Interactive API docs (Swagger) are auto-generated at <http://localhost:8000/docs>.

### Docker (API + dashboard)

```bash
docker compose up --build
```

- API: <http://localhost:8000> (docs at `/docs`)
- Operator console: <http://localhost:8080>

SQLite and the write-ahead audit log persist in the `causalcut-data` volume.

---

## API reference (`/api/v1`)

Ingestion & state (spine):

| Method & path | Description |
|---------------|-------------|
| `GET  /health`, `/ready`, `/stats` | Liveness, readiness (checks WAL + queue saturation), counters by information class |
| `POST /events/ingest` | Ingest one canonical event (validate → tag → persist → queue) |
| `POST /events/ingest/batch` | Ingest a batch; partial success, one result row per event |
| `GET  /events`, `/events/{id}` | Read the append-only event store |
| `GET  /events/dead-letter/list` | Events that failed downstream processing |
| `GET  /state/zones/{zone}` | Materialised zone state (sensors, workers, permits) |
| `GET  /state/permits`, `/state/workers`, `/state/sensors/{id}/history` | Plant-state projections |

Risk, approval & handover (analytical half):

| Method & path | Auth | Description |
|---------------|------|-------------|
| `GET  /risk/paths` | — | Active accident pathways (engine view) |
| `GET  /risk/recommendation` | — | Current minimum causal cut (or none) |
| `POST /risk/approve` | **shift_officer+** | Approve / reject / defer; write-ahead audited |
| `GET  /risk/audit` | — | Tail the hash-chained audit log + verify the chain |
| `POST /handover/validate` | — | Validate a shift handover against live state |

Approval authenticates via the `X-API-Key` header.

### ⚠️ Development keys

The approval gateway ships with **development keys** so the demo runs out of the
box:

| Key | Operator | Role |
|-----|----------|------|
| `dev-key-so-a` | SO-A | shift_officer |
| `dev-key-so-b` | SO-B | shift_officer |
| `dev-key-sm-01` | SM-01 | safety_manager |
| `dev-key-viewer` | VIEW-01 | viewer |

**Local demo only.** In any real deployment set `CAUSALCUT_OPERATORS` (see
`.env.example`) and remove the dev keys. Keys are stored only as SHA-256 hashes
and compared in constant time. (Separately, `CAUSALCUT_API_KEY` optionally guards
the ingest write endpoint.)

---

## The minimum-causal-cut formulation (design doc §6)

Each activated hyperedge decomposes into one or more **accident sub-pathways**,
each a conjunction of *necessary* factors (e.g. a flash fire needs
`gas_source ∧ ignition_source`). Breaking **any one** necessary factor breaks
that route. Given candidate interventions (each removing a set of factors):

```
minimise   Σ_j (w_cost·cost_j + w_disruption·disruption_j
                + w_latency·latency_j + w_cardinality) · x_j
s.t.       every live sub-pathway is broken by ≥ 1 chosen intervention
           residual_risk(x) ≤ safety_threshold
           x_j ∈ {0, 1}
```

Solved with OR-Tools CP-SAT (greedy fallback if OR-Tools is unavailable, and an
emergency zone-closure fallback if no feasible cut exists). `w_cardinality`
dominates, steering the solver toward few, cheap, low-disruption actions rather
than blanket closures.

---

## Information-class discipline

Every event carries one of six information classes and they are never silently
reclassified: `M` measured · `P` predicted · `S` synthetic · `C` counterfactual ·
`R` regulatory · `H` human. The schema enforces the invariants (a measurement can
never be synthetic; a prediction must name its model; a counterfactual must carry
non-zero uncertainty). Risk scores are `P` and are deliberately absent — not
defaulted to a comforting `0.0` — until the engine computes them.

---

## Safety posture & MVP boundary (design doc §9)

- **Recommend-only.** No autonomous actuation; every action needs an
  authenticated human approval.
- **Durability before dispatch.** Events are written to the append-only store
  *before* being queued, so a full queue or a crashed consumer degrades to
  "persisted, awaiting replay" — never data loss. Append-only is enforced by a
  database trigger, not by convention.
- **Auditable.** Approvals are appended to a write-ahead, hash-chained log;
  `GET /risk/audit` re-verifies the whole chain and reports the first bad
  sequence number if any record was tampered with.
- **Deterministic decisions.** The risk arithmetic and intervention selection are
  fully deterministic (rules + CP-SAT). The gas projection is monotonic by event
  time, so out-of-order delivery under concurrent consumers cannot regress state.

This is an MVP blueprint: rules and thresholds are hand-authored and the plant
model is the bundled Steelforge topology. Production would add learned
forecasters, a real historian feed, and PostgreSQL — all behind the same
contracts in `app/schemas/canonical.py`.

---

## Tests

```
50 passed
  · 26  ingestion spine (schema invariants, WAL, idempotency, persist-before-queue,
         projection, dead-letter, append-only enforcement, OpenAPI)
  · 21  analytical half (hypergraph, compound-rule activation, sub-pathway
         extraction, minimum-cut incl. "avoid the sledgehammer", handover rules,
         audit hash-chain + tamper detection)
  ·  3  end-to-end integration (ingest → project + risk from the same stream →
         authenticated, audited approval; handover endpoint)
```

## Repository layout

```
app/
  schemas/     canonical event + enums + ingest contracts (Pydantic V2)
  db/          WAL SQLite session, schema.sql, repositories
  queue/       async EventQueue + ConsumerPool (StateProjector + RiskEngine hook)
  api/v1/      routes: health, events, state, risk
  core/        config, logging, middleware, exceptions
  engine/      hypergraph, compound rules, path extractor, cut optimiser,
               types (engine domain model), adapter, risk_engine
  gateway/     auth (role tiers), audit_log (write-ahead, hash-chained)
  analysis/    handover validator
dashboard/     React operator console (Vite + nginx)
scripts/       seed_scenario.py
scenarios/     coke_oven.json
tests/         test_day1, test_hypergraph, test_compound_rules, test_handover,
               test_integration
```

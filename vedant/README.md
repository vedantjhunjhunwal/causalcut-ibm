# CAUSALCUT

**CAUSALCUT — Minimum-Causal-Cut Safety Twin for Industrial Plants**

A defensive industrial-safety "safety twin" for a steel plant. CAUSALCUT ingests a live stream of plant events, maintains a materialised plant-state store, models the plant as a dynamic **safety hypergraph**, detects **compound accident chains**, and computes the **minimum set of interventions** that breaks every high-risk pathway — subject to cost, disruption, and human-approval constraints.

---

## Architecture Overview

CAUSALCUT is a **modular monolith** divided into three logical layers:

1. **Ingestion Spine**: 
   - Built on FastAPI.
   - Enforces a canonical `SafetyEvent` schema.
   - Uses an asyncio queue with backpressure and dead-lettering.
   - Maintains plant-state via a SQLite WAL state store.
2. **Analytical Engine**: 
   - Safety hypergraph using NetworkX.
   - Evaluates compound rules and risk propagation.
   - Uses OR-Tools for minimum causal cut optimization.
   - Counterfactual simulation (SimPy).
3. **Approval Gateway**: 
   - Role-based Auth service (e.g., shift_officer, safety_manager).
   - Manages operator approval/rejection.
   - Maintains a hash-chained tamper-evident audit log.

---

## Model Availability Matrix

| Model | Type | Artifacts | Status |
|-------|------|-----------|--------|
| Gas (XGBoost + IsolationForest) | Classification + Anomaly | `.models/XGB Classifier/`, `.models/Isolation Forest Anomaly Detector/` | ✅ REAL |
| Hydraulic (LightGBM multi-output) | Multi-target classification | `.models/Hydraulic Classifier/` | ✅ REAL |
| Machine Failure (AI4I LightGBM) | Multi-label classification | `.models/AI4I Classifier/` | ✅ REAL |
| Vision (YOLOv8 PPE) | Object detection | requires torch | ⚠️ Degraded (needs torch) |
| Tracking (ByteTrack) | Multi-object tracking | requires torch | ⚠️ Degraded (needs torch) |
| Regulatory RAG (FAISS) | Retrieval + verification | `regulatory_rag/` | ⚠️ Degraded without faiss-cpu |

---

## Quick Start (Local Development)

```bash
# Backend
pip install -r requirements.txt -r requirements-full.txt
uvicorn app.main:app --reload --port 8000

# Dashboard (separate terminal)
cd dashboard && npm install && npm run dev

# Run the Coke Oven scenario
python scripts/seed_scenario.py
```

---

## Docker Deployment

```bash
docker compose up --build
# API: http://localhost:8000  Dashboard: http://localhost:4000  Model Server: http://localhost:9000
```

---

## API Endpoints

**Health:**
- `GET /health`
- `GET /ready`
- `GET /stats`

**Ingestion:**
- `POST /events/ingest`
- `POST /events/batch`
- `GET /events/{id}`

**Plant State:**
- `GET /state/zones`
- `GET /state/permits`
- `GET /state/workers`
- `GET /state/sensors`

**Risk:**
- `GET /risk/paths`
- `GET /risk/recommendation`
- `POST /risk/approve`
- `GET /risk/audit`

**Scenario:**
- `POST /scenario/run`
- `POST /scenario/validate`
- `GET /scenario/template`
- `GET /scenario/samples`

**Models:**
- `POST /models/gas/predict`
- `POST /models/machine-failure/predict`
- `POST /models/hydraulic/predict`
- `GET /models/status`

**Causal Cut:**
- `GET /causal-cut/recommend`
- `POST /causal-cut/simulate`

---

## Scenario Format

Scenarios are defined using a structured JSON schema. It contains declarations for zones, sensors, workers, permits, and an event stream (like gas readings). 
You can retrieve a blank template by hitting the `/scenario/template` endpoint or by viewing `scenarios/blank_template.json`.

---

## Test Suite

The comprehensive test suite (approx 20 files, 219 passing tests) covers:
- **Real:** Ingestion spine, validation, canonical events, fresh-graph pipeline, compound rules, path extraction, OR-Tools cut, risk propagation, SimPy sim, graph API, SQLite WAL, model execution (XGBoost, LightGBM).
- **Mocked:** Vision inference and tracker.
- **Logically verified:** Interactive graph UX, form flows.
- **Skipped:** Tests requiring remote live model server or torch when unavailable in the sandbox.

---

## Environment Variables

Copy `.env.example` to `.env` to override configuration defaults. 
Key variables include:
- `CAUSALCUT_ENVIRONMENT`: dev, staging, prod
- `CAUSALCUT_DB_PATH`: SQLite database location
- `CAUSALCUT_CORS_ORIGINS`: Allowed origins (e.g. `http://localhost:4000`)
- `CAUSALCUT_MACHINE_MODEL_DIR`: Path to the AI4I LightGBM model (`.models/AI4I Classifier`)
- Remote Model URLs: (e.g. `CAUSALCUT_GAS_MODEL_API_URL`)

---

## Project Structure

```text
app/
  schemas/     canonical event + scenario (Pydantic V2)
  db/          WAL SQLite session, schema.sql
  queue/       async EventQueue + ConsumerPool
  api/v1/      routes: health, events, state, risk, scenario, models
  core/        config, logging, middleware
  engine/      hypergraph, compound rules, cut optimiser, risk_engine
  gateway/     auth, write-ahead audit_log
  analysis/    handover validator
  services/    model_service.py (inference wrappers)
  simulation/  counterfactual sim (SimPy)
dashboard/     React operator console (Vite)
scenarios/     templates and samples
tests/         test suite
.models/       trained model artifacts
regulatory_rag/FAISS index and verifier
```

# CAUSALCUT

### Minimum-Causal-Cut Safety Twin for Industrial Plants

CAUSALCUT is a defensive industrial-safety **"safety twin"** for heavy-process plants (built around a steel-plant / coke-oven scenario). It ingests a live stream of plant events, maintains a materialised model of the plant's current state, represents the plant as a dynamic **safety hypergraph**, detects **compound accident chains** before they complete, and computes the **minimum set of interventions** that breaks every high-risk pathway — subject to cost, operational-disruption, and human-approval constraints.

The core idea in one sentence: *most industrial accidents are not caused by a single failure but by several individually-tolerable conditions overlapping in the same place at the same time — so the right unit of analysis is the **combination**, and the right response is the **smallest cut** that severs it.*

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [The Core Concept](#2-the-core-concept-in-depth)
3. [System Architecture](#3-system-architecture)
4. [The Model Stack](#4-the-model-stack)
5. [The Agentic AI Layer](#5-the-agentic-ai-layer)
6. [Tech Stack](#6-tech-stack)
7. [Repository Layout](#7-repository-layout)
8. [Getting Started](#8-getting-started)
9. [Running Scenarios](#9-running-scenarios)
10. [API Reference](#10-api-reference)
11. [Configuration](#11-configuration)
12. [Testing](#12-testing)

---

## 1. The Problem

A modern process plant is instrumented with hundreds of sensors and governed by dozens of permits and procedures. The failure mode that classic alarm systems handle badly is the **compound hazard**:

> Rising combustible-gas concentration in a zone is *yellow*.
> An active hot-work (welding) permit in that zone is *yellow*.
> A worker present without the correct PPE is *yellow*.
> Ventilation degrading below nominal is *yellow*.
>
> All four overlapping in the same zone at the same time is the **coke-oven flash-fire pathway** — and no single-signal alarm sees it coming.

Traditional systems alarm on individual thresholds, drowning operators in isolated yellow alerts while the genuinely dangerous *conjunction* goes unranked. CAUSALCUT is built to reason about those conjunctions explicitly, and — crucially — to tell an operator not just *"you are in danger"* but *"here is the smallest, cheapest, least-disruptive set of actions that removes the danger."*

---

## 2. The Core Concept (In Depth)

CAUSALCUT rests on four ideas that compose into a single pipeline.

### 2.1 The Safety Hypergraph

An ordinary graph connects two nodes with an edge. That is too weak to model a plant, because hazards are *multi-way* relationships. CAUSALCUT models the plant as a **hypergraph**, where a single **hyperedge** can bind an arbitrary set of nodes — zones, sensors, permits, workers, assets — into one dangerous relationship.

A hyperedge like `HE-042` ("coke-oven flash fire") is not a static wire; it is a *latent* structure that becomes **activated** only when all of its constituent conditions hold simultaneously in the live plant state. The hypergraph is rebuilt/refreshed from the current state on each analysis pass, so it is a true *twin* of the plant as it is right now, not a fixed diagram.

### 2.2 Compound Rules — detecting the conjunction

The **compound rule engine** (`app/engine/compound_rules.py`) holds a library of `CompoundRule` templates. Each rule is a set of **predicate functions** over the current graph state plus a **severity function**. On every evaluation pass the engine tests each rule's predicates against live state and, where they all hold, *materialises a concrete activated hyperedge* with a computed severity.

This is what turns four independent "yellow" signals into one identified, named, ranked "red" pathway.

### 2.3 Spatiotemporal Risk Propagation

Danger does not stay where it starts. The **risk propagator** (`app/engine/risk_propagator.py`) assigns each zone *i* a scalar risk level `R_i(t) ∈ [0, 1]`. Risk is **injected** locally by hazard events (gas-anomaly severity, equipment-failure severity drawn from the canonical event stream) and then **diffuses** to neighbouring zones through the plant topology graph, decaying with distance. This captures shared-utility coupling — e.g. a common ventilation duct or gas main that lets a hazard in one zone raise the risk of an adjacent one.

The **path extractor** (`app/engine/path_extractor.py`) then turns an activated hyperedge into a human-readable **accident chain**: a directed subgraph from *source conditions* (rising gas, ignition source) through *contributing factors* (missing PPE, degraded ventilation) to the *potential outcome* (flash fire / toxic exposure), annotated with the zones the risk can propagate to.

### 2.4 The Minimum Causal Cut — the heart of the system

This is where the name comes from. Given:

- the set of **active accident paths** (each a set of contributing factors), and
- the set of **candidate interventions** (each of which breaks some subset of factors, at some cost),

CAUSALCUT solves for the **smallest / cheapest set of interventions that breaks every critical factor** and pushes residual risk below the safety threshold.

Formally this is a **weighted set-cover / minimum-cut** problem, solved with **Google OR-Tools CP-SAT** (`app/engine/cut_optimiser.py`). If OR-Tools is unavailable, the system falls back to a **greedy set-cover** so it still returns a safe (if non-optimal) recommendation rather than failing. The optimiser is deliberately **stateless and pure** — same inputs always yield the same cut — which makes it testable and auditable.

Instead of "shut everything down," the operator gets: *"Halt the hot-work permit in Zone 3 and restore ventilation to nominal — those two actions alone break every active pathway."*

### 2.5 Counterfactual Simulation

Before a recommendation is trusted, the **counterfactual simulator** (`app/simulation/counterfactual_sim.py`, built on **SimPy**) can play the proposed cut forward in a discrete-event model of the plant to confirm the intervention set actually drives residual risk below threshold under the scenario's dynamics.

### 2.6 The Human-Approval Gateway

CAUSALCUT never acts autonomously on the plant. Every recommendation passes through an **approval gateway** (`app/gateway/`) with **role-based auth** (e.g. `shift_officer`, `safety_manager`) and a **hash-chained, tamper-evident audit log**, so every recommendation, approval, and rejection is recorded in a verifiable chain. This keeps a human in the loop and produces a defensible record.

---

## 3. System Architecture

CAUSALCUT is a **modular monolith** organised into three logical layers.

```
          ┌───────────────────────── EVENT SOURCES ─────────────────────────┐
          │  gas / machine / hydraulic sensors · permits · worker telemetry  │
          └────────────────────────────────┬────────────────────────────────┘
                                            │  canonical SafetyEvent stream
                                            ▼
 ╔══════════════════════════ 1 · INGESTION SPINE ══════════════════════════╗
 ║  FastAPI  ·  SafetyEvent schema validation                              ║
 ║  asyncio queue (backpressure + dead-lettering)                          ║
 ║  materialised plant state  →  SQLite WAL state store                    ║
 ╚════════════════════════════════════════╤════════════════════════════════╝
                                           ▼
 ╔══════════════════════════ 2 · ANALYTICAL ENGINE ════════════════════════╗
 ║  Safety Hypergraph (NetworkX)                                           ║
 ║  Compound-rule evaluation  →  activated hyperedges                      ║
 ║  Spatiotemporal risk propagation  →  R_i(t) per zone                    ║
 ║  Accident-path extraction                                              ║
 ║  Minimum-causal-cut optimiser (OR-Tools CP-SAT → greedy fallback)      ║
 ║  Counterfactual simulation (SimPy)                                     ║
 ║  + ML model services  ·  + multi-agent AI layer                        ║
 ╚════════════════════════════════════════╤════════════════════════════════╝
                                           ▼
 ╔══════════════════════════ 3 · APPROVAL GATEWAY ═════════════════════════╗
 ║  Role-based auth (shift_officer / safety_manager)                       ║
 ║  Operator approve / reject                                             ║
 ║  Hash-chained tamper-evident audit log                                 ║
 ╚════════════════════════════════════════╤════════════════════════════════╝
                                           ▼
                        React + Vite dashboard  ·  live graph, risk, recommendations
```

**Layer 1 — Ingestion Spine.** A FastAPI service enforces a canonical `SafetyEvent` schema, buffers events through an asyncio queue with backpressure and dead-lettering, and maintains the materialised plant state in a SQLite WAL store.

**Layer 2 — Analytical Engine.** The hypergraph, compound rules, risk propagation, path extraction, causal-cut optimiser, and counterfactual simulation described above — plus the ML model services and the agentic AI layer.

**Layer 3 — Approval Gateway.** Role-based auth, operator approval/rejection, and the hash-chained audit log.

A separate **model server** (`model_server/server.py`) hosts the heavier ML models behind an HTTP interface so the main app can call them as a service; a React dashboard renders the live graph, risk map, and recommendations.

---

## 4. The Model Stack

CAUSALCUT fuses classical ML models with the graph engine. Each model degrades gracefully — if its libraries or artifacts are missing, the system reports it as unavailable rather than crashing.

| Model | Type | Libraries | Powers |
|-------|------|-----------|--------|
| **Gas** | XGBoost classifier + Isolation-Forest anomaly detector | `xgboost`, `scikit-learn` | Gas-hazard classification and anomaly scoring |
| **Hydraulic** | LightGBM multi-output classifier | `lightgbm` | Multi-target hydraulic-condition classification |
| **Machine Failure** | AI4I LightGBM multi-label classifier | `lightgbm` | Equipment-failure-mode prediction |
| **Vision (PPE)** | YOLOv8 object detection | `torch`, `ultralytics` | Detecting missing PPE from camera frames |
| **Tracking** | ByteTrack multi-object tracking | `torch`, `supervision`, `lapx` | Following workers across frames |
| **Regulatory RAG** | FAISS retrieval + verification | `faiss-cpu`, `sentence-transformers` | Grounding recommendations in regulatory text |

The gas, hydraulic, and machine models are lightweight tabular models that load from the `.models/` artifacts and run **in-process**. The vision, tracking, and RAG models are heavier and optional — install `requirements-full.txt` to enable them.

---

## 5. The Agentic AI Layer

On top of the deterministic engine, CAUSALCUT runs a **multi-agent system** (`app/agents/`) coordinated over an internal message bus, with shared memory and a tool-calling interface. The LLM provider is **Google Gemini** (`llm_provider = "gemini"`, default model `gemini-3.6-flash`), with `local` and `mock` providers available for offline/testing runs.

| Agent | Role |
|-------|------|
| **Supervisor** | Orchestrates the other agents and summarises the current plant situation |
| **Sentinel** | Continuous monitoring — watches plant state and raises alerts. *Deterministic/statistical, does **not** use the LLM for detection* |
| **Planning** | Proposes intervention plans |
| **Reasoning** | Analyses accident chains and causal structure |
| **Learning** | Adapts over time; sensor-drift detection via ADWIN (`river`) |
| **Compliance** | Checks recommendations against regulatory constraints |
| **Chat** | Operator-facing natural-language interface with tool calling — answers questions about live plant state |

> **Design note:** hazard *detection* is intentionally kept in the deterministic engine (compound rules + risk math), not the LLM. The agents add explanation, planning, compliance-checking, and a conversational interface *around* a verifiable core — the LLM never silently decides whether the plant is safe.

---

## 6. Tech Stack

**Backend**
- **FastAPI** — API and ingestion spine
- **Pydantic v2** / **pydantic-settings** — schema validation and config
- **NetworkX** — hypergraph representation
- **Google OR-Tools (CP-SAT)** — minimum-causal-cut optimisation
- **SimPy** — discrete-event counterfactual simulation
- **SQLite (WAL mode)** — materialised plant-state store
- **Supabase** — hosted persistence / auth backing
- **httpx** — async HTTP (model-server calls)
- **python-json-logger** — structured logging

**Machine Learning**
- **XGBoost**, **LightGBM**, **scikit-learn** — tabular models
- **PyTorch** + **Ultralytics YOLOv8** — vision
- **supervision** + **lapx** — ByteTrack tracking
- **FAISS** + **sentence-transformers** — regulatory RAG
- **river** — online ADWIN drift detection

**Agentic AI**
- **Google Gemini** (`google-genai`) — reasoning, planning, chat

**Frontend (dashboard/)**
- **React 18** + **Vite** + **Tailwind CSS**
- **ReactFlow** + **dagre** — live hypergraph visualisation
- **Plotly** (`react-plotly.js`) — risk/telemetry charts
- **react-router-dom**, **react-markdown** + **remark-gfm**
- **@supabase/supabase-js** — realtime data

**Tooling & Ops**
- **pytest** / **pytest-asyncio** — test suite
- **Docker Compose** — API + dashboard + model-server orchestration

---

## 7. Repository Layout

```
app/
├── api/            FastAPI routers (v1 routes: events, risk, scenario, models, ...)
├── core/           Config, settings, logging
├── db/             SQLite WAL session + Supabase repositories
├── engine/         Hypergraph, compound rules, risk propagation, path extraction,
│                   cut optimiser, drift monitor, scenario pipeline/runner
├── optimizer/      Causal-cut solver
├── simulation/     SimPy counterfactual simulator
├── agents/         Multi-agent system (supervisor, sentinel, planning, ...)
├── gateway/        Role-based auth + hash-chained audit log
├── analysis/       Handover validation
├── schemas/        Canonical SafetyEvent + scenario schemas
├── services/       Model services + remote model client
└── queue/          Async ingestion queue

model_server/       Standalone HTTP model server (heavy models)
regulatory_rag/     FAISS store + regulatory documents
.models/            Trained tabular-model artifacts
.datasets/          Training/reference datasets
scenarios/          Sample scenario JSON files
scripts/            seed_scenario.py and utilities
dashboard/          React + Vite frontend
tests/              Test suite
docker/             Container definitions
```

---

## 8. Getting Started

### Prerequisites
- **Python 3.11+**
- **Node.js 18+** (for the dashboard)
- **Docker** (optional but recommended for the full demo)

### ⚠️ Fix before installing

`requirements.txt` ships with a redundant `google-generativeai>=0.8.0` line. It is **not used by the code** (the code imports the newer `google-genai` SDK), and it forces `protobuf < 6`, which conflicts with the pinned `protobuf >= 6.33.1` and makes the install fail with a misleading `ortools`/`protobuf` resolution error. **Delete that one line** from `requirements.txt` before installing. Keep `google-genai>=1.0.0` and the `protobuf` pin.

### Install & run the backend (venv)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-full.txt

cp .env.example .env               # then add your Gemini key (see Configuration)
uvicorn app.main:app --reload --port 8000
```

Then open the interactive API docs at **http://localhost:8000/docs**.

> **Lighter install:** `requirements.txt` alone gives you the API and the in-process tabular models (gas, hydraulic, machine). Add `requirements-full.txt` only when you need the vision/tracking/RAG stack — it pulls PyTorch + CUDA wheels (several GB).

### Run the dashboard (separate terminal)

```bash
cd dashboard
npm install
npm run dev
```

### Recommended: full stack via Docker

Running `uvicorn` alone starts the API and in-process models, but **full scenario runs also need the model server** (otherwise `/scenario/run` returns a connection error). Docker Compose brings up all three services wired together:

```bash
docker compose up --build
# API:          http://localhost:8000
# Dashboard:    http://localhost:4000
# Model Server: http://localhost:9000
```

---

## 9. Running Scenarios

A scenario is a structured JSON document declaring the plant's **zones, zone adjacency, assets, sensors**, sensor readings (**gas / machine / hydraulic**), **workers, permits**, and an **event stream**, plus a `safety_threshold`.

```bash
# Fetch a blank template
curl http://localhost:8000/api/v1/scenario/template

# Seed and run the bundled coke-oven scenario
python scripts/seed_scenario.py
```

Sample scenarios live in `scenarios/` (e.g. `coke_oven.json`, `simple_gas_leak.json`, `h2_compressor_nightshift.json`). Validate a scenario before running it with `POST /api/v1/scenario/validate`.

> **Note on schema:** different sample files target slightly different schema versions. Use `GET /api/v1/scenario/template` as the source of truth for the current expected shape, and `POST /api/v1/scenario/validate` to check a file before `POST /api/v1/scenario/run`.

---

## 10. API Reference

All routes are served under the `/api/v1` prefix. Explore them live at `/docs`.

**Health** — `GET /health` · `GET /ready` · `GET /stats`

**Ingestion** — `POST /events/ingest` · `POST /events/batch` · `GET /events/{id}`

**Plant State** — `GET /state/zones` · `GET /state/permits` · `GET /state/workers` · `GET /state/sensors`

**Risk** — `GET /risk/paths` · `GET /risk/recommendation` · `POST /risk/approve` · `GET /risk/audit`

**Scenario** — `POST /scenario/run` · `POST /scenario/validate` · `GET /scenario/template` · `GET /scenario/samples`

**Models** — `POST /models/gas/predict` · `POST /models/machine-failure/predict` · `POST /models/hydraulic/predict` · `GET /models/status`

**Causal Cut** — `GET /causal-cut/recommend` · `POST /causal-cut/simulate`

---

## 11. Configuration

Configuration is via environment variables (see `.env.example`). Key settings:

| Variable | Purpose |
|----------|---------|
| `CAUSALCUT_LLM_PROVIDER` | `gemini` · `local` · `mock` |
| `CAUSALCUT_LLM_MODEL` | LLM model name (default `gemini-3.6-flash`) |
| `CAUSALCUT_LLM_API_KEY` | Gemini API key — required for blueprint/chat/agent features |
| `*_MODEL_API_URL` | If set, the backend calls that model as a **remote** HTTP service instead of running it in-process |
| Supabase keys | Hosted persistence / auth |

Without an LLM key the app still runs — the Gemini-powered features fall back to mock/degraded responses, while the deterministic engine and tabular models work normally.

---

## 12. Testing

```bash
pytest
```

The suite covers the ingestion spine, schema validation, canonical events, the fresh-graph pipeline, compound-rule evaluation, path extraction, the OR-Tools cut, risk propagation, SimPy simulation, the graph API, the SQLite WAL store, and in-process model execution (XGBoost / LightGBM).

---

*CAUSALCUT is a defensive safety-analysis system: it exists to identify and break dangerous conditions, keeps a human in the approval loop for every recommendation, and records every decision in a tamper-evident audit trail.*

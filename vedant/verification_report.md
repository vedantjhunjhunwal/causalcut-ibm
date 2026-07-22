# CAUSALCUT — Verification Report (v1.6)

Only the listed acceptance gaps were changed; working modules were preserved.

---

## 1. Issues fixed

| # | Issue | Resolution | Verified |
|---|---|---|---|
| 1 | **Analysis ran on incomplete state** — a queue timeout still produced a Minimum Causal Cut | Fail-closed gate before `analyse_graph()`. On timeout / rejected event / queue-full / projection error the pipeline returns `status:"failed"` with `recommendation:null`, `activated_rules:[]`, `graph:null`, `analysis_performed:false`; route returns **504** (timeout) or **422** (ingestion). | Real |
| 2 | **Gas classifier output marked `MEASURED`** | Now `information_class = P` with `model_name`, `model_version`, `confidence`, `inference_mode`, `latency_ms`, `degraded_reason`, `scenario_id`, `correlation_id`, `artifact_path`. Raw 128-dim array tagged `raw_input_class:"measured"`. | Real |
| 3 | **Remote readiness trusted `/health`** — a healthy server made every model look available | `RemoteModelService.status()` now queries `/api/v1/models/status` and returns *that model's* entry (`registry_key` per subclass), with `ready`, `artifact_found`, `dependency_status`, `load_status`, `degraded_reason`. | Real (live server) |
| 4 | Inference gated on `available` (import-only) rather than full readiness | All `predict/detect/update` entrypoints now gate on `readiness()` (artifact + deps + load + smoke). Fixed a self-recursion this introduced. | Real |
| 5 | Machine tests demanded `> 0.5` | Removed everywhere. Tests now assert the **artifact contract**: probabilities in [0,1], expected target keys, `failure_modes` from the configured threshold, `top_failure_mode` = argmax, dict-order independence, JSON-serialisable. | Real |
| 6 | Vision/tracking were standalone API calls only | `Scenario` extended with `vision_inputs[]` (image_b64 / image_ref / frame_id) and `tracking_inputs[].detections[]` (validated frame_id, bbox[4], class, confidence∈[0,1]). Both flow through the shared services → canonical events → ingestion → queue → SQLite → hypergraph. | Real |
| 7 | WebSocket broadcast every run to every client | New `/api/v1/ws/scenarios/{run_id}` (run-scoped). `POST /scenario/start` returns **202** with `run_id`/`scenario_id`/`correlation_id` immediately and executes in the background; `GET /scenario/runs/{run_id}` is the polling fallback. Legacy firehose kept for debugging. | Real |
| 8 | Docker lacked the model/RAG stack | `Dockerfile.modelserver` installs the full pinned stack (CPU torch index), bakes artifacts + FAISS index + metadata + embedding config, and tolerates a **missing YOLO checkpoint** (build succeeds; vision/tracking report unavailable). | Config only |

## 2. Coke Oven flow — verified end to end

```
POST /api/v1/scenario/start            → 202  run_id + scenario_id + correlation_id
WS   /api/v1/ws/scenarios/{run_id}     → persisting_events, queue_processing,
                                          state_projection, hypergraph_update,
                                          rule_evaluation, path_extraction,
                                          optimization, risk_propagation, …
GET  /api/v1/scenario/runs/{run_id}    → status: completed
   analysis_performed True · ingested 5 · processed 5 · failed 0 · queue_depth 0
   RULES  HE-042:zone-1, HE-IGNITION-UNGUARDED:zone-1, HE-TOXIC-EXPOSURE:zone-1
   CUT    Suspend PTW-007 · Evacuate W-003
   CITES  DGMS-Circ-PTW 2.1 (lexical_bm25 over the real 241-chunk corpus)
POST /scenario/{run}/decision APPROVE  → 200, audit_seq 18; duplicate → 409
GET  /risk/audit                       → chain_valid: true
```

## 3. Test results — **253 passed · 6 failed · 1 skipped**

| Area | Classification |
|---|---|
| Queue timeout prevents analysis; failed projection prevents recommendation | **Real** |
| Gas events marked predicted (+ operator gas stays observed) | **Real** |
| Per-model remote readiness; vision/tracking not falsely ready | **Real** |
| Machine-model artifact contract | **Real** |
| Vision/tracking scenario schema + validation + degraded mode | **Real** |
| Background run (202), run-scoped WebSocket, polling fallback | **Real** |
| SQLite projection before analysis; append-only persistence | **Real** |
| Rule identity HE-042; propagation; SimPy; OR-Tools | **Real** |
| Operator approval / rejection / duplicate prevention / audit chain | **Real** |
| Regulatory retrieval over the real corpus | **Real (lexical tier)** — semantic tier **not runnable** |
| Full Coke Oven flow to audit log | **Real** |
| `test_yolo_detector.py` (6 failures) | **Not runnable** — `torch` unavailable |
| Scenario-pipeline-over-remote (1 skipped) | **Logically verified** — see `scripts/verify_remote_models.sh` |
| Docker service connectivity | **Not runnable** — no Docker daemon; compose parses, wiring complete |
| Frontend panels + WS reconnect/fallback | **Logically verified** — production build passes (188 modules) |

Note: the stressed machine fixture returns **0.7496** with the artifact shipped
here (not 0.3366 — that value came from a differently-trained artifact). Tests
no longer depend on either number.

## 4. Commands

```bash
# local
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-full.txt
uvicorn app.main:app --reload --port 8000
cd dashboard && npm install && npm run dev      # http://localhost:4000

# docker (model-server wiring active by default)
docker compose up --build                       # api :8000 · models :9000 · ui :4000

# tests
pytest -q
pytest tests/test_acceptance_v16.py -q          # fail-closed, gas semantics, WS isolation
pytest tests/test_pipeline_ordering.py -q       # persistence before analysis
bash scripts/verify_remote_models.sh
```

## 5. Remaining limitations

1. **Vision + tracking unavailable** (`torch`, `ultralytics`, `supervision` not
   installable here). They report `ready:false` with the exact missing
   dependency and generate **zero** events. The 6 test failures are these.
2. **RAG runs in the lexical tier** — real corpus, real citations, BM25 ranking.
   `pip install sentence-transformers` promotes it to semantic FAISS.
3. **Docker not executed** — no daemon available. Compose parses; the CPU-torch
   install path and container-to-container calls are unverified here.
4. **Frontend not browser-tested** — production build only.
5. Run store is in-memory; operator decisions persist to the audit log, but run
   history is not yet a SQLite table.

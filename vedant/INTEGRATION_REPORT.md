# CAUSALCUT — Integration Report

## 1. Executive Summary

This report outlines the current accurate integration state of the CAUSALCUT pipeline, covering ML models, the scenario runner, and analytical engines. A significant amount of functionality that was previously degraded or missing has now been fully implemented.

The application operates as a **modular monolith** with three primary layers (Ingestion Spine, Analytical Engine, Approval Gateway). All core workflows including compound rule evaluation, risk propagation, scenario execution, and minimum causal cut optimization are fully functional.

## 2. Component Status

| Component | Status | Notes |
|---|---|---|
| Ingestion Spine (FastAPI, SQLite WAL, Queue) | ✅ Complete | Fully tested with idempotency and append-only constraints. |
| Scenario Runner | ✅ Complete | Fresh-graph pipeline builds dynamic hypergraphs. |
| Analytical Engine (NetworkX Hypergraph) | ✅ Complete | Successfully evaluates rules, propagates risk. |
| OR-Tools CP-SAT Optimiser | ✅ Complete | Minimum causal cut solver functioning and tested. |
| Approval Gateway & Audit Log | ✅ Complete | Hash-chained tamper-evident audit log operating correctly. |
| React Dashboard | ✅ Complete | Interactive React Flow safety hypergraph built and communicating. |
| Counterfactual Simulator | ✅ Complete | Time-to-harm and intervention baseline simulation works. |

## 3. Model Inference Status

Model implementations have been thoroughly verified and integrated with both in-process and remote model server capabilities.

| Model | Classification | Evidence |
|---|---|---|
| Gas (XGBoost + IsolationForest) | ✅ REAL | Artifact loaded (`model_1&2.joblib`), pipeline leverages real features. In-process and remote transports tested. |
| Hydraulic (LightGBM multi-output) | ✅ REAL | Artifact loaded, handles real features natively. In-process and remote transports tested. |
| Machine Failure (AI4I LightGBM) | ✅ REAL | Artifact obtained and loaded. Correctly issues failure modes. In-process and remote transports tested. |
| Regulatory RAG (FAISS) | ⚠️ Degraded | Missing `faiss-cpu` and `sentence-transformers` in current environment; falls back to static clause mapping. |
| Vision (YOLOv8) | ❌ Unavailable | Requires `torch` and `ultralytics` which are absent. |
| Tracking (ByteTrack) | ❌ Unavailable | Requires `torch` which is absent. |

## 4. Pipeline Coverage

- **Canonical schema:** Successfully validated custom zones, referential integrity.
- **Model Events:** Scenarios process model events naturally into the `SafetyHypergraph` without mock fabrication.
- **Causal Cut Evaluation:** Causal paths and optimization interventions are produced correctly under tested scenarios.

## 5. Known Limitations

- **Hardware Dependencies:** Vision (YOLOv8) and Tracking features cannot run locally without GPU-enabled PyTorch or a properly configured model server.
- **RAG Dependencies:** The FAISS compliance verifier runs in degraded mode (using static rules) until vector-search dependencies are installed.
- **In-Memory Store:** The current scenario run state is held in-memory (per-process dictionary), though approval decisions correctly write to the on-disk SQLite DB and audit logs.

## 6. Test Coverage Summary

- **Total Suite:** 219 tests passed, 6 failed, 1 skipped.
- The 6 failing tests are all strictly tied to the missing YOLOv8 torch dependencies.
- **Validations include:** Schema enforcement, SQLite WAL concurrency, API boundaries, path extraction logic, model integration layer, remote client fallbacks.

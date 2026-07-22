# CAUSALCUT Model Inference API

All model endpoints live under `/api/v1/models` and are served by the **shared
inference service layer** (`app/services/model_service.py`). The scenario
orchestrator calls those same singletons in-process — model loading and
preprocessing exist in exactly one place, and no localhost HTTP hop is used.

Swagger/OpenAPI: `http://localhost:8000/docs`

## Response envelope

Every prediction returns the same JSON-serialisable envelope:

| field | meaning |
|---|---|
| `model_name` | service identifier, e.g. `gas_xgboost_isoforest` |
| `model_version` | artifact version, e.g. `xgb-gas-1&2-1.0` |
| `prediction` | model output (never raw tensors/DataFrames/numpy) |
| `confidence` | 0–1 where the model exposes one, else `null` |
| `inference_mode` | `real` \| `degraded` \| `unavailable` \| `mock` |
| `latency_ms` | measured inference latency |
| `degraded_reason` | why real inference did not run (else `null`) |
| `correlation_id` | request correlation ID (also in structured logs) |
| `scenario_id` | when invoked from a scenario |
| `artifact_path` | the artifact actually loaded |
| `timestamp` | UTC ISO-8601 |

**A degraded response never contains a fabricated prediction** — `prediction`
is `null` and `degraded_reason` explains the gap.

## Execution modes

- `real` — artifact + dependencies present, real inference ran.
- `degraded` — some models unavailable; every available model still runs, and
  unavailable ones are reported. No substitute predictions are invented.
- `mock` — **tests only**. Never selected implicitly by the scenario workflow
  (`models.mocks_used` is `false` in every production response).

Configured via `CAUSALCUT_MODEL_EXECUTION_MODE` (`auto` default).

## Endpoints

### `GET /models/health` · `GET /models/status` · `GET /models/readiness`
No auth. `status` returns per-model `available`, `artifact_path`,
`inference_mode`, `degraded_reason`; `readiness` splits models into
available/unavailable.

### `POST /models/gas/predict`
XGBoost gas classifier + IsolationForest drift detector (CPU).

- **Feature order/dimension:** exactly **128** floats — the UCI Gas Sensor
  Array Drift layout, 16 sensors × 8 features
  (`dR, abs_dR, EMAi0.001, EMAi0.01, EMAi0.1, EMAd0.001, EMAd0.01, EMAd0.1`),
  sensor-major. Preprocessing (the fitted scaler bundled in the artifact) is
  applied inside the service.
- **Artifact:** `.models/XGB Classifier/model_1&2.joblib` +
  `.models/Isolation Forest Anomaly Detector/gas_sensor_isoforest_pipeline.joblib`

```json
// request
{ "features": [0.12, -0.4, ...128 values...], "sensor_id": "GS-03", "zone_id": "zone-1" }
// response (abridged)
{ "model_name": "gas_xgboost_isoforest", "model_version": "xgb-gas-1&2-1.0",
  "prediction": { "event_type": "gas_anomaly", "gas_type": "ethanol",
                  "concentration_ppm": 4853.8, "drift_detected": true,
                  "anomaly_score": -0.31, "gas_class_probabilities": {...} },
  "confidence": 0.9752, "inference_mode": "real", "latency_ms": 42.1 }
```

Errors: `422 invalid_features` (wrong dimension), `503 model_unavailable`.

### `POST /models/machine-failure/predict`
AI4I 2020 LightGBM with Platt-calibrated probabilities.

- **Artifact:** `.models/AI4I Classifier/lgbm-ai4i-1.0_pipelines.joblib`
  (override with `CAUSALCUT_MACHINE_MODEL_DIR`). There are **no separate
  scaler/encoder files** — the `MinMaxScaler` (continuous) and `OneHotEncoder`
  (`Type`) live inside the fitted sklearn Pipeline, so the training
  preprocessing is applied automatically.
- **Feature order:** read from the artifact's fitted preprocessor
  (`feature_names_in_`), not hardcoded — `["Type", "Air_temperature",
  "Process_temperature", "Rotational_speed", "Torque", "Tool_wear"]`.
  Input dict ordering is irrelevant; the service builds the frame in trained
  order. A missing feature returns `422` naming the required order.
- **Failure modes:** `Machine_failure` (combined), `TWF` tool wear, `HDF` heat
  dissipation, `PWF` power, `OSF` overstrain, `RNF` random.
  A mode is listed in `failure_modes` when its probability ≥
  `CAUSALCUT_MODEL_CONFIDENCE_THRESHOLD` (default 0.5).

```json
// request
{ "Type": "L", "Air_temperature": 302.0, "Process_temperature": 310.2,
  "Rotational_speed": 1300, "Torque": 58.0, "Tool_wear": 200 }

// response (abridged)
{ "model_name": "machine_failure_ai4i_lgbm", "model_version": "lgbm-ai4i-1.0",
  "prediction": { "machine_failure": 0.749588, "top_failure_mode": "OSF",
                  "failure_modes": ["OSF", "HDF"],
                  "probabilities": { "Machine_failure": 0.749588, "TWF": 0.001781,
                                     "HDF": 0.660927, "PWF": 0.000205,
                                     "OSF": 0.847823, "RNF": 0.002 } },
  "failure_modes": ["OSF", "HDF"],
  "probabilities": { "...": 0.0 },
  "confidence": 0.847823, "inference_mode": "real", "latency_ms": 100.2,
  "degraded_reason": null, "artifact_path": ".../lgbm-ai4i-1.0_pipelines.joblib" }
```

All values are native JSON types (no numpy scalars). If the artifact is absent
the endpoint returns `503` with `prediction: null`, `failure_modes: []`,
`probabilities: {}` and a `degraded_reason` — never a fabricated probability.
Retrain with `python ".models/AI4I Classifier/training_pipeline.py"`.

In the scenario pipeline, `machine_readings[]` are routed through this same
shared service; the prediction becomes an `equipment_failure` canonical event
carrying `failure_probability`, `failure_mode`, `failure_modes` and
`mode_probabilities`, which flows into the hypergraph asset node and can
activate mechanical compound rules (e.g. `HE-MECH-EXPOSURE`).

### `POST /models/hydraulic/predict`
LightGBM multi-output over 17 sensors (`PS1..PS6, EPS1, FS1, FS2, TS1..TS4,
VS1, CE, CP, SE`). The service computes the trained statistical features
(mean/median/max/min/std/skew per sensor) itself — send raw cycle arrays.
Artifact: `.models/Hydraulic Classifier/lgbm-hydraulic-1.0_pipelines.joblib`.

### `POST /models/vision/detect` · `POST /models/tracking/update`
YOLOv8 PPE detection and ByteTrack re-identification. Require `torch` +
`models/yolov8_ppe.pt`; otherwise `503` with `degraded_reason`.

### `POST /models/regulatory/verify`
FAISS RAG compliance verification over the shipped index
(`regulatory_rag/faiss_store/regulatory.index`). Requires `faiss-cpu` +
`sentence-transformers`; without them it returns `inference_mode: "degraded"`
with a static clause map (clearly flagged, never presented as FAISS evidence).

## How the scenario pipeline uses these

Supply **raw model inputs** in the scenario and the orchestrator routes them
through the services before any canonical event exists:

- `gas_readings[].features` (128 floats) → gas model → `gas_anomaly` /
  `sensor_drift` canonical event
- `machine_readings[]` → machine model → `equipment_failure` event
- `hydraulic_readings[].sensor_data` → hydraulic model → `utility_condition` event

A `gas_readings` entry **without** `features` is treated as an operator-entered
MEASURED value and is *not* attributed to any model.

Every run response includes:

```json
"execution_mode": "real|degraded",
"models": { "invocations": [...], "models_called": [...], "models_ran": [...],
            "models_failed": [...], "mocks_used": false, "registry_status": {...} }
```

which the dashboard renders in the **Model Inference Provenance** panel.

## Environment

```
CAUSALCUT_MODEL_EXECUTION_MODE=auto     # auto | real | degraded | mock(tests)
CAUSALCUT_MODEL_DEVICE=cpu              # cpu | cuda
CAUSALCUT_MODEL_CONFIDENCE_THRESHOLD=0.5
CAUSALCUT_MODEL_REQUEST_TIMEOUT_S=10.0
CAUSALCUT_MODEL_RETRY_COUNT=1
CAUSALCUT_MODEL_RETRY_BACKOFF_S=0.25
# artifact overrides
CAUSALCUT_GAS_XGB_MODEL_PATH= / CAUSALCUT_GAS_ISOFOREST_MODEL_PATH=
CAUSALCUT_HYDRAULIC_MODEL_DIR= / CAUSALCUT_MACHINE_MODEL_DIR= / CAUSALCUT_VISION_MODEL_PATH=
# remote model services (optional)
CAUSALCUT_GAS_MODEL_API_URL= / CAUSALCUT_MACHINE_MODEL_API_URL= / ...
```

---

## Remote model-server mode

Models can run **in-process** (default) or on a **separate model server**. Both
use the same shared service layer, so only the transport differs.

```
in-process : Frontend → FastAPI backend → model service → local artifact
remote     : Frontend → FastAPI backend → HTTP → model server → artifact
```

### Run the model server

```bash
uvicorn model_server.server:app --host 0.0.0.0 --port 9000
curl -s localhost:9000/api/v1/models/readiness | python -m json.tool
```

### Point the backend at it

```bash
export CAUSALCUT_GAS_MODEL_API_URL=http://localhost:9000/api/v1/models/gas/predict
export CAUSALCUT_MACHINE_MODEL_API_URL=http://localhost:9000/api/v1/models/machine-failure/predict
export CAUSALCUT_HYDRAULIC_MODEL_API_URL=http://localhost:9000/api/v1/models/hydraulic/predict
export CAUSALCUT_MODEL_REQUEST_TIMEOUT_S=10.0
export CAUSALCUT_MODEL_RETRY_COUNT=2
export CAUSALCUT_MODEL_RETRY_BACKOFF_S=0.25
uvicorn app.main:app --port 8000
```

Any model **without** a URL stays in-process — the modes mix freely (e.g. run
YOLO remotely on a GPU box, keep the tabular models local).

`GET /api/v1/models/status` reports `transport: "remote" | "in_process"` per
model, and each prediction carries `transport`, `remote_url` and
`remote_latency_ms` alongside the wall-clock `latency_ms`.

### Docker

`docker-compose.yml` includes a `model-server` service (built from
`Dockerfile.modelserver`). Uncomment the `CAUSALCUT_*_MODEL_API_URL` block
under `api` to switch to remote mode.

### Failure behaviour

Transport errors are retried with exponential backoff
(`retries`, `backoff_s`). If every attempt fails the client returns
`inference_mode: "degraded"` with `prediction: null` and a `degraded_reason`
naming the transport error. **A remote failure never fabricates a prediction.**
A `422` from the server is surfaced immediately (no retry) as
`InvalidFeaturesError`.

### Verify

```bash
bash scripts/verify_remote_models.sh
```

Starts the model server, runs the full scenario pipeline through it, and
asserts the gas model ran remotely.

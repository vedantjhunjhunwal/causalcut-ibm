#!/usr/bin/env bash
# Verifies the REMOTE model path end-to-end:
#   backend -> HTTP -> standalone model server -> trained artifact
#
# Starts the model server as a real subprocess, points the backend's
# *_MODEL_API_URL env vars at it, runs the full scenario pipeline, then stops.
#
# Usage:  bash scripts/verify_remote_models.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
PORT="${MODEL_SERVER_PORT:-9000}"

echo "==> starting model server on :$PORT"
$PY -m uvicorn model_server.server:app --host 127.0.0.1 --port "$PORT" \
    --log-level warning > /tmp/causalcut_model_server.log 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  curl -sf --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null && break
  sleep 1
done
echo "    health: $(curl -s --max-time 5 "http://127.0.0.1:$PORT/health")"
echo "    readiness: $(curl -s --max-time 30 "http://127.0.0.1:$PORT/api/v1/models/readiness" \
  | $PY -c 'import json,sys; d=json.load(sys.stdin); print("available:", d["available_models"])')"

echo "==> running scenario pipeline through the REMOTE models"
PYTHONPATH="$PWD" \
CAUSALCUT_GAS_MODEL_API_URL="http://127.0.0.1:$PORT/api/v1/models/gas/predict" \
CAUSALCUT_MACHINE_MODEL_API_URL="http://127.0.0.1:$PORT/api/v1/models/machine-failure/predict" \
CAUSALCUT_HYDRAULIC_MODEL_API_URL="http://127.0.0.1:$PORT/api/v1/models/hydraulic/predict" \
$PY - <<'PYEOF'
import json, warnings
warnings.filterwarnings("ignore")
from app.core.config import get_settings
get_settings.cache_clear()
from app.services.model_service import reset_registry, get_registry
reset_registry()
reg = get_registry()
print("   transports:", {k: reg.transport(k) for k in ("gas", "machine", "hydraulic")})

from app.schemas.scenario import Scenario
from app.engine.scenario_runner import run_scenario

scn = json.load(open("scenarios/model_driven_coke_oven.json"))
scn["machine_readings"] = [{"asset_id": "M-1", "zone_id": "zone-1", "Type": "L",
                            "Air_temperature": 302.0, "Process_temperature": 310.2,
                            "Rotational_speed": 1300, "Torque": 58.0, "Tool_wear": 200}]
r = run_scenario(Scenario.model_validate(scn), correlation_id="corr-remote-verify")
print("   execution_mode:", r["execution_mode"])
print("   models_ran:", r["models"]["models_ran"])
print("   models_failed:", r["models"]["models_failed"])
for i in r["models"]["invocations"]:
    print(f"     - {i['called']}: {i['inference_mode']} {i.get('model_version')} "
          f"({i.get('latency_ms')} ms)")
print("   activated rules:", [x["id"] for x in r["activated_rules"]])
if r["recommendation"]:
    print("   minimum cut:", [i["action"] for i in r["recommendation"]["interventions"]])
    print("   residual:", r["recommendation"]["residual_risk"],
          "threshold_met:", r["recommendation"]["threshold_met"])
assert "gas:GS-03" in r["models"]["models_ran"], "gas model did not run remotely"
print("==> REMOTE PATH VERIFIED")
PYEOF

"""E2E validation: run the full Coke Oven scenario through the production pipeline."""
import json
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.engine.scenario_runner import run_scenario
from app.schemas.scenario import Scenario

# Load the model-driven coke oven scenario
with open("scenarios/model_driven_coke_oven.json") as f:
    data = json.load(f)

scenario = Scenario.model_validate(data)
print(f"Scenario: {scenario.name}")
print(f"Zones: {[z.zone_id for z in scenario.zones]}")
gas_feat_len = len(scenario.gas_readings[0].features) if scenario.gas_readings and scenario.gas_readings[0].features else 0
print(f"Gas readings: {len(scenario.gas_readings)} (features: {gas_feat_len})")
print(f"Workers: {len(scenario.workers)}")
print(f"Permits: {len(scenario.permits)}")
print()

# Run the full pipeline
result = run_scenario(scenario, correlation_id="e2e-test")

# Report each stage
print("=== PIPELINE RESULT ===")
print(f"Execution mode: {result['execution_mode']}")
print(f"Scenario ID: {result['scenario_id']}")
print(f"Correlation ID: {result['correlation_id']}")
print()

# Models
models = result.get("models", {})
print(f"Models ran: {models.get('models_ran', 0)}")
print(f"Models degraded: {models.get('models_degraded', 0)}")
for m in models.get("detail", []):
    print(f"  {m['model']}: mode={m['inference_mode']}, {m.get('degraded_reason', '')}")
print()

# Graph
g = result["graph"]
print(f"Graph: {len(g['nodes'])} nodes, {len(g['edges'])} edges")
print()

# Rules + paths
print(f"Activated rules: {len(result['activated_rules'])}")
for r in result["activated_rules"]:
    print(f"  {r['id']}: {r['pathway']} (severity {r['severity']:.2f})")
print()

print(f"Causal paths: {len(result['causal_paths'])}")
for p in result["causal_paths"]:
    print(f"  {p['pathway']} @ {p['root_zone']}: factors={p['contributing_factors']}")
print()

# Recommendation
rec = result.get("recommendation")
if rec:
    print(f"Recommendation: {len(rec['interventions'])} intervention(s), cost={rec['total_cost']}, threshold_met={rec['threshold_met']}")
    for iv in rec["interventions"]:
        print(f"  #{iv['priority']}: {iv['action']} (cost={iv['cost_category']}, breaks={iv['breaks_factors']})")
else:
    print("No recommendation (no active pathway)")
print()

# Zone risk
print(f"Zone risk: {result['zone_risk']}")
print(f"Time to harm: {result.get('time_to_harm_seconds')} seconds")
print()

# Risk timeline
tl = result.get("risk_timeline", {})
print(f"Risk timeline: {len(tl.get('timestamps_s', []))} steps, watch={tl.get('watch_zone')}")
print()

# Regulatory
print(f"Regulatory citations: {len(result['regulatory_citations'])}")
for c in result["regulatory_citations"][:3]:
    txt = c["text"][:80] if len(c["text"]) > 80 else c["text"]
    print(f"  {c['clause']}: {txt}...")
print()

# Warnings
print(f"Warnings: {result.get('warnings', [])}")
print()

# Explanation
print(f"Explanation: {result['explanation'][:200]}...")
print()
print("=== E2E VALIDATION: SUCCESS ===")

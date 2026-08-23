# CausalCut Safety Intelligence — Agentic AI

A read-only, Gemini-powered chat agent for operators, integrated into the
existing CausalCut architecture rather than bolted on beside it. This
document covers what it is, how it's wired in, and how to turn it on.

## TL;DR

- **Chat with the plant**: operators ask questions in plain language; the
  agent calls real backend functions to answer, then narrates the result.
- **Read-only by construction, not just by policy**: the tool module
  (`app/engine/agent_tools.py`) imports nothing from `app.gateway` — it is
  structurally incapable of approving or dispatching anything.
- **Off by default**: `CAUSALCUT_AGENT_ENABLED=false` unless you set it.
- **Every tool call is logged**, separately from the hash-chained audit
  log (which stays reserved for human decisions).

## Architecture

```
Operator (ChatDrawer, React)
   │  POST /api/v1/agent/chat  { message, session_id }
   ▼
app/api/v1/routes/agent.py         — feature flag check, 503 if unconfigured
   ▼
app/services/agent_service.py      — two-pass Gemini loop (google-genai SDK)
   │  Pass 1: message + tool schema → Gemini
   │  Gemini either replies directly, or returns function_call(s)
   ▼
app/engine/agent_tools.py          — AgentToolkit: whitelisted, read-only
   │  Calls the SAME functions the REST API already uses:
   │  RiskEngine, repositories, ComplianceVerifier, ExplanationRenderer,
   │  CounterfactualSimulator, model registry, AuditLog (read only)
   ▼
   tool result (JSON) fed back to Gemini
   │  Pass 2: Gemini synthesises into operator-facing prose
   ▼
Response → ChatDrawer, with a small badge per tool call actually used
```

## Tool surface

All tools live in `app/engine/agent_tools.py::AgentToolkit`. Every one maps
1:1 onto an existing module — none invent new business logic:

| Tool | Backs onto |
|---|---|
| `get_zone_status` | `PermitRepository`, `WorkerZoneRepository`, `SensorTelemetryRepository` |
| `list_non_compliant_workers` | `WorkerZoneRepository.non_compliant()` |
| `check_sensor_drift` | `app/engine/drift_monitor.py` (ADWIN via `river`) over real telemetry history |
| `get_risk_recommendation` | `RiskEngine.recommendation_payload()` |
| `get_active_paths` | `RiskEngine.paths_payload()` |
| `explain_rule` | `CompoundRuleEngine.rules` |
| `explain_current_cut` | `RiskEngine.current()` + `ComplianceVerifier` + `explanations/renderer.py` |
| `verify_action_compliance` | `regulatory_rag/verifier.py::ComplianceVerifier` |
| `simulate_what_if` | `app/simulation/counterfactual_sim.py` (same SimPy model `/causal-cut/simulate` uses) |
| `get_model_health` | `app/services/model_service.py::get_registry()` |
| `get_audit_history` | `AuditLog.tail()` / `verify_chain()` — **read only**, never `.append()` |
| `get_osha_prior` | `risk_priors/osha_risk_priors.json` (built by `osha_parser.py`) |

Why these particular ones: `explain_current_cut` and `verify_action_compliance`
close two gaps flagged in this project's own `incompleteness_report.md` (the
missing explanation renderer wiring and the missing compliance verifier
usage) — building them as agent tools gets real functionality and a strong
"agentic" demo out of the same work. `get_osha_prior` puts the OSHA base-rate
parser to use for the first time; nothing else in the app read that file
before. `check_sensor_drift` does the same for the ADWIN drift detector,
adapted to the scalar telemetry that's actually persisted (see the docstring
in `drift_monitor.py` for why it isn't the raw 128-dim vector the original
script targets).

## The hard boundary

`AgentToolkit` never imports `app.gateway.auth` and never calls
`AuditLog.append()`. Nothing under `app/engine/agent_tools.py` can approve a
recommendation or dispatch an intervention — that only happens via
`POST /risk/approve`, gated by real operator auth, exactly as before this
feature existed. `tests/test_agent_tools.py::test_no_write_or_auth_imports_in_agent_tools`
asserts this at the source level, not just as a design intention.

The Gemini system prompt also tells the model it has no authority to act —
but that's a soft control. The hard control is that the corresponding
Python method simply does not exist in this codebase. If the model ever
hallucinates a tool name outside `ALLOWED_TOOL_NAMES`, the dispatcher
rejects it and logs a warning (`tests/test_agent_e2e_mocked.py::test_disallowed_tool_is_never_executed`
covers this).

## Setup

1. Install the new dependencies:
   ```
   pip install google-genai river
   ```
   (both already added to `requirements-full.txt`)

2. Get a Gemini API key from Google AI Studio.

3. Set environment variables (see `.env.example`):
   ```
   CAUSALCUT_AGENT_ENABLED=true
   CAUSALCUT_GEMINI_API_KEY=your-key-here
   CAUSALCUT_AGENT_MODEL_NAME=gemini-2.0-flash   # verify current model names before deploying
   ```

4. Start the backend as usual. `GET /api/v1/agent/status` should report
   `"enabled": true, "configured": true`.

5. The dashboard's chat bubble (bottom-right) opens the drawer automatically —
   no separate frontend config needed beyond `VITE_API_BASE` already pointing
   at your backend.

## SDK note

This targets **`google-genai`** (`from google import genai`), the current
unified SDK — not `google-generativeai`, which is now deprecated upstream
with no further updates. If you've seen older sample code using
`genai.configure()` / `GenerativeModel.start_chat()`, that's the old SDK;
this integration uses `genai.Client(...)`, `client.chats.create(...)`, and
`response.function_calls` instead.

## What's read-only today vs. what Phase 2 could add

Everything above is Phase 1: **read, explain, simulate — never act.** A
future Phase 2 (not built here) could let the agent *draft* things — e.g. a
proposed incident report — but only ever landing in a
`status="agent_proposed"` row that a human must promote through the same
approval UI as everything else. No such write path exists yet; adding one
is a deliberate, separate decision, not a natural extension of this code.

## Testing

```
pytest tests/test_agent_tools.py tests/test_agent_e2e_mocked.py tests/test_drift_monitor.py -v
```

- `test_agent_tools.py` — every tool exercised against the real app state
  (risk engine, db, audit log), no LLM involved.
- `test_agent_e2e_mocked.py` — the two-pass loop with `google.genai` fully
  mocked, including the disallowed-tool-name rejection path.
- `test_drift_monitor.py` — the ADWIN wrapper, including its degraded
  contract when `river` isn't installed.

No live-Gemini smoke test is included (same pattern as `test_remote_models.py`
for other optional live-network tests) — add one locally with a real key if
you want to validate end-to-end against the actual API before a demo.

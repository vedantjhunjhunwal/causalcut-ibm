# CAUSALCUT → Dynamic Barrier-Optimized Safety Twin
## Technical Gap Analysis and Migration Specification

**Prepared for:** ET AI Hackathon 2026 — Problem Statement 1 (AI-Powered Industrial Safety Intelligence for Zero-Harm Operations)
**Document type:** Current-state / goal-state / migration plan
**Scope:** Backend analytical engine, data model, agentic layer, geospatial layer, RAG layer

---

## 1. Purpose and Method

This document specifies what must change in CAUSALCUT to close the gap between the current implementation and (a) the literal requirements of the problem statement, and (b) the formalism used by production process-safety systems in industry (bow-tie / LOPA / dynamic barrier management), so that the system's design vocabulary and technical claims are defensible under expert questioning.

Every gap below is stated as: **current state → goal state → change required → why it matters for judging/defensibility**. Changes are ordered by priority, where priority is determined by (1) coverage of an explicitly-named deliverable in the problem statement that is currently at zero, (2) cost of implementation within a hackathon timeframe, (3) contribution to the "Innovation" and "Technical Excellence" judging criteria (45% combined weight).

---

## 2. Executive Summary of Gaps

| # | Area | Current State | Goal State | Priority |
|---|---|---|---|---|
| G1 | Formal risk model | Ad hoc hypergraph + rule engine, no named methodology | Bow-tie / LOPA-conformant model (threats → barriers → top event → consequences), hypergraph as the *execution substrate* under a recognized formalism | P0 |
| G2 | Reasoning architecture | Deterministic rule engine (`CompoundRuleEngine`) only | Deterministic core retained, wrapped by a thin multi-agent orchestration layer for detection correlation, response drafting, and pattern mining | P0 |
| G3 | Geospatial fidelity | 6-node abstract SVG graph, no real coordinates | Georeferenced zone polygons anchored to actual blueprint pixel/coordinate space, real worker/sensor positions plotted spatially | P0 |
| G4 | Incident/near-miss intelligence | RAG covers only regulatory text (OISD/DGMS/Factories Act) | Second RAG corpus over historical incident and near-miss reports, with pattern-surfacing endpoint | P0 |
| G5 | Emergency response automation | Human-in-the-loop approval only; no drafted response artifacts | Agent-drafted (not agent-executed) evacuation/alert/incident-report package generated automatically on confirmed high-severity path, still gated by existing approval chain | P1 |
| G6 | Barrier health as first-class state | Barrier status is a binary event type (`barrier_status`) | Barrier objects carry live health/degradation state (bypass status, last-proof-test age, demand count) analogous to industry "Live Barrier Health" | P1 |
| G7 | Continuous compliance | Regulatory verification is on-demand, per-recommendation | Continuous background compliance scorecard against plant state, independent of an active accident path | P2 |
| G8 | Vision pipeline | YOLOv8/ByteTrack stubbed (`needs torch`), non-functional | Either made functional on CPU-feasible models, or explicitly reframed as a roadmap item with a working substitute for the demo | P2 |
| G9 | Forecasting | Not implemented (documented as future work in source doc §4.1) | Minimal Prophet/SARIMA forecast feeding predicted `[P]` events into the existing pipeline unchanged | P2 |

P0 = must-fix before pitch; directly closes a named deliverable gap or a credibility risk under expert questioning.
P1 = strongly recommended; high leverage relative to effort.
P2 = stretch goal; valuable if time remains, defensible to leave as "future work" if not.

---

## 3. G1 — Formal Risk Model: Hypergraph → Bow-Tie/LOPA Conformance

### 3.1 Current State

The `SafetyHypergraph` (NetworkX `MultiDiGraph`) models `ZONE`, `SENSOR`, `WORKER`, `EQUIPMENT`, `BARRIER`, `PERMIT` nodes with edges `in_zone`, `monitors`, `applies_to`, `protects`, `adjacent`, `held_by`. The `CompoundRuleEngine` (Stage 7) evaluates fixed predicate combinations (`rising_gas()`, `active_permit()`, `worker_missing_ppe()`, `ventilation_degraded()`, `barrier_down()`, `equipment_failing()`) against this graph to activate compound hyperedges, which `PathExtractor` (Stage 8) decomposes into `AccidentPath` objects.

This is structurally a bow-tie diagram — it has causes (threats), consequences, and barriers — but it is not *named*, *documented*, or *exposed* as one anywhere in the architecture, the API, or the dashboard. This has three concrete costs:

1. **Judges and domain experts will not recognize the contribution.** Bow-tie/LOPA is the terminology every process-safety engineer, DGMS/OISD auditor, and industrial judge on an evaluation panel will use to assess "regulatory compliance coverage" (an explicit evaluation criterion). A system that reinvents the formalism without naming it reads as either unaware of the domain standard or, worse, as if it's hiding a weaker ad hoc model behind different words.
2. **No traceability to PHA source documents.** Real bow-ties are derived from HAZOP/HAZID studies and are auditable back to those studies. CompoundRuleEngine rules (HE-042, HE-TOXIC-EXPOSURE, etc.) currently have no declared provenance — there's no field indicating which HAZOP worksheet, which historical incident, or which OISD clause each rule encodes.
3. **No distinction between preventive and mitigative barriers.** Bow-tie formalism requires classifying each barrier as either preventive (stops the top event from occurring) or mitigative (limits consequences after it occurs). `CandidateIntervention` objects (`revoke permit`, `isolate gas line`, `evacuate zone`, `dispatch PPE`) are currently undifferentiated — the optimizer treats "prevent the fire" and "get people out after it starts" as the same kind of action, which is both formally wrong and operationally dangerous to conflate in a real recommendation.

### 3.2 Goal State

Every `CompoundRule` is reframed and re-documented as a **Bow-Tie Definition**:

```
BowTie {
  hazard_id: str                    # e.g. "coke-oven-flash-fire"
  top_event: str                    # the loss-of-control event, e.g. "ignition of accumulated CO/H2"
  threats: List[ThreatNode]         # causal preconditions (existing predicate builders)
  preventive_barriers: List[Barrier]   # stop threat -> top event
  mitigative_barriers: List[Barrier]   # limit top event -> consequence
  consequences: List[ConsequenceNode]
  source_reference: str             # HAZOP worksheet ID / OISD clause / historical incident ID
}
```

`CandidateIntervention` gains a `barrier_role: Literal["preventive", "mitigative"]` field. This is not a cosmetic rename — it changes the CP-SAT objective function (§5 below), because a minimum-cost cut that only selects mitigative barriers while threats remain active is a materially worse recommendation than one that closes preventive barriers first, and the current formulation cannot distinguish these cases.

The existing 5 compound rules (HE-042, HE-TOXIC-EXPOSURE, HE-GAS-ACCUMULATION, HE-IGNITION, HE-MECHANICAL) map directly onto 5 bow-ties with no loss of existing logic — this is a re-labeling plus one new required field per rule (`source_reference`), not a rewrite.

### 3.3 Change Required

| Component | Change |
|---|---|
| `CompoundRuleEngine` | Add `source_reference` and `barrier_role` metadata to each rule definition. No change to predicate evaluation logic. |
| `CandidateIntervention` schema | Add `barrier_role: Literal["preventive","mitigative"]` |
| `AccidentPath` | Add `top_event: str` field (currently implicit in the causal subgraph, not surfaced) |
| Dashboard — Risk Paths view | Render as bow-tie layout (threats-left, top-event-center, consequences-right) as an alternative view mode alongside the existing ReactFlow causal graph, using the same underlying `AccidentPath` data — no new backend data needed |
| Regulatory RAG | Link `source_reference` to actual retrievable OISD/DGMS clause text via existing `/api/verify` |

### 3.4 Effort

Low. This is schema extension plus a rename/relabel pass and one new dashboard view mode reusing existing ReactFlow infrastructure with a different layout algorithm (still Dagre-compatible, different orientation). No changes to NetworkX graph structure, no changes to Stage 6-11 execution logic.

---

## 4. G2 — Reasoning Architecture: Deterministic-Only → Deterministic Core + Thin Agent Layer

### 4.1 Current State

CompoundRuleEngine is a fixed set of composable predicates evaluated deterministically over the hypergraph. This is correct engineering for the safety-critical detection path — non-negotiable, and should not be replaced. However:

- The problem statement's suggested technology list names **"Agentic AI / Multi-Agent Systems"** explicitly, and three of the six "what you may build" bullets (Compound Risk Detection Engine, Emergency Response Orchestrator, Quality & Compliance Audit Agent) describe agentic behavior.
- CAUSALCUT currently has exactly one agentic component: the read-only AI Assistant chat drawer (Gemini 3.1 Flash Lite), which is decoupled from the pipeline — it can answer questions about state but does not participate in detection, response drafting, or pattern analysis.
- This is a real architectural risk under questioning: a judge who asks "where is the multi-agent system" gets, currently, "we have a chatbot" as the honest answer.

### 4.2 Goal State — Design Constraint First

**The deterministic core must remain deterministic.** Do not replace CompoundRuleEngine, PathExtractor, or MinimumCausalCutOptimiser with LLM reasoning. This would be a regression, not an improvement: CP-SAT gives a provably optimal or bounded-suboptimal solution with a certificate; an LLM agent gives a plausible-sounding one with no guarantee. The correct architecture is agents *around* the deterministic core, not *instead of* it — this is also the technically correct answer if a judge probes on why you didn't "just use an LLM for everything," which is a predictable question.

Three narrow, well-scoped agents, each consuming deterministic pipeline output and producing a bounded artifact:

**Agent 1 — Response Drafting Agent** (addresses "Emergency Response Orchestrator")
- Trigger: `CutRecommendation` with `residual_risk` above a severity threshold on a confirmed (non-degraded) accident path.
- Input: the `AccidentPath`, the `CutRecommendation`, plant topology, and the regulatory RAG.
- Output: a structured, non-executing draft — evacuation zone list, alert message drafts per channel (SMS/PA/dashboard banner), and a preliminary DGMS/OISD-formatted incident report skeleton pre-filled with the `[M]`/`[P]` event chain that triggered it.
- Constraint: **the agent proposes, it does not act.** All physical interventions still route through the existing JWT/HMAC role-gated approval gateway and hash-chained audit log unchanged. This is the correct safety posture and should be stated explicitly and proactively in the pitch — an autonomous agent that can trigger evacuation without human confirmation is itself a hazard (false positive at 3am evacuates a live coke oven floor), and the design choice to keep it proposal-only is a defensible, judge-legible trade-off, not a limitation to apologize for.

**Agent 2 — Incident Pattern Agent** (addresses "Incident Pattern Intelligence")
- Consumes the new near-miss/incident RAG corpus (G4).
- Runs on a schedule (not per-event), cross-referencing accumulated `AccidentPath` history against historical incident patterns to surface recurring precursor combinations not yet encoded as a `CompoundRule`.
- Output: candidate new bow-tie definitions for human safety-engineer review — this closes the loop between "system finds a pattern" and "pattern becomes a codified, auditable rule," which is the actual differentiator over a black-box anomaly detector.

**Agent 3 — Compliance Audit Agent** (addresses "Quality & Compliance Audit Agent," G7)
- Runs continuously against plant state (not only against active accident paths), independent of Stage 7-11.
- Produces a compliance scorecard: which OISD/DGMS clauses are currently satisfied, which are at risk given current barrier health, which permits are approaching a compliance boundary.

### 4.3 Change Required

| Component | Change |
|---|---|
| New service: `agent_orchestrator` | Thin FastAPI service or module consuming pipeline events via the existing WebSocket/event bus — does not sit in the critical Stage 1-12 path, so it cannot introduce latency or failure modes into the fail-closed detection pipeline |
| `CutRecommendation` | No schema change required — Agent 1 subscribes to existing output |
| New endpoint `/agent/response-draft` | Returns Agent 1 output |
| New endpoint `/agent/patterns` | Returns Agent 2 output (candidate bow-ties) |
| New endpoint `/agent/compliance-scorecard` | Returns Agent 3 output |
| Dashboard | New "Response Draft" panel in Approvals view; new "Patterns" view; compliance scorecard in Regulations view |

### 4.4 Effort

Medium. All three agents are read-only consumers of existing pipeline state — none requires modifying Stage 1-12. The main cost is prompt/schema design and the near-miss corpus (shared with G4). This is deliberately architected so agent failures (LLM timeout, bad output) cannot degrade the safety-critical deterministic pipeline — a hard requirement, not a nice-to-have, given the existing fail-closed design principle already in the codebase.

---

## 5. G3 — Geospatial Fidelity: Abstract Graph → Georeferenced Blueprint Overlay

### 5.1 Current State

The Zone Map view renders 6 zones as an interactive SVG with fixed abstract topology (zone-1 through zone-6, connections as declared in the adjacency table in the source document). This is a **topology graph**, not a **geospatial map** — there are no coordinates, no scale, no relationship to actual plant floor area, and Blueprint Canvas (Gemini Vision blueprint → zone extraction) currently feeds the Scenario Lab's fresh hypergraph construction, not this view.

This is the single clearest gap against the problem statement, because "Geospatial Safety Analytics" appears in the theme title itself, and "Geospatial Safety Heatmap" is the second explicitly named buildable component. An abstract 6-node colored graph will not be read as geospatial by a judge, regardless of how good the underlying risk math is.

### 5.2 Goal State

Blueprint Canvas output is repurposed as the **source of spatial ground truth** for the primary risk visualization, not merely a Scenario Lab input:

1. Gemini Vision extraction returns zone boundaries as **pixel-space polygons** referenced to the uploaded blueprint image (already close to what Blueprint Canvas does for topology extraction — the change is retaining and exposing polygon vertices instead of collapsing to a zone list).
2. A `SpatialZone` record stores `{zone_id, polygon: List[Point2D], image_ref, scale_reference}` — `scale_reference` from either a user-provided known-distance calibration (e.g., "this wall is 40m") or, if absent, left in blueprint-pixel space with an explicit disclaimer rather than a fabricated real-world scale (**do not silently invent a scale — an [S]-class assumption must be tagged as such per CAUSALCUT's own Information Classification Framework, which already has a category for exactly this**).
3. Risk Propagator (Stage 9) output — the continuous `R_i(t)` value per zone — renders as a **heat overlay directly on the blueprint image** (polygon fill, red-to-green gradient) instead of on an abstract SVG shape. This is the literal "Geospatial Safety Heatmap" deliverable, implemented with data you already compute.
4. `WORKER` nodes, currently tracked only as `worker_zones` (which zone a worker is in), get an optional `(x, y)` field within the zone polygon when CCTV/tracking data provides it, or default to zone-centroid placement when it does not — this degrades gracefully rather than requiring the full vision pipeline (G8) to be functional.

### 5.3 Change Required

| Component | Change |
|---|---|
| Blueprint Canvas / Gemini Vision extraction | Retain polygon vertices in extraction output; currently likely collapsed to zone metadata only — needs verification against actual current extraction schema |
| New table: `spatial_zones` | `{zone_id, polygon_points, image_ref, scale_reference, scale_confidence}` |
| Risk Propagator output consumption | No change to Euler diffusion math — only the rendering layer changes |
| Dashboard — Zone Map view | Replace fixed SVG with image-anchored polygon overlay (e.g., SVG `<polygon>` elements positioned in the blueprint image's coordinate space, or a canvas-based heat layer) |
| `information_class` tagging | Any position without a real calibration reference is tagged `[S]` (Synthetic) per the existing framework — this is not new infrastructure, just correct application of a system CAUSALCUT already has |

### 5.4 Effort

Medium. The Euler diffusion risk math (Stage 9) is completely unchanged — this is a rendering-layer and data-model change, not an analytical-engine change. The main new work is the polygon extraction/calibration flow and the frontend overlay component. Given React 19 + the existing SVG-based Zone Map, this is a substitution of the coordinate source, not a rewrite of the rendering approach.

---

## 6. G4 — Incident Pattern Intelligence: Regulatory-Only RAG → Dual-Corpus RAG

### 6.1 Current State

The Regulatory RAG microservice (port 5005, FAISS `IndexFlatIP`, MiniLM-L6-v2 embeddings, Gemini 2.0 Flash generation) indexes exactly one corpus type: OISD-STD-105/114/137, Factories Act 1948, DGMS Circulars. It answers "is this recommendation compliant" — it does not answer "has this precursor combination happened before, and what happened."

"Incident Pattern Intelligence" is a named deliverable in the problem statement (RAG-powered agent cross-referencing near-miss reports, historical incident data, and regulatory guidance) and is currently unaddressed.

### 6.2 Goal State

A second FAISS index, same embedding model, over a corpus of:
- Publicly available industrial incident summaries (DGFASLI annual reports, DGMS circular incident annexes, news-verified incident writeups such as the ones already researched for this project's own pitch — Visakhapatnam, Bhilai, Clairton coke oven incidents)
- Synthetic near-miss reports generated to match CAUSALCUT's own `AccidentPath` schema, since real proprietary near-miss logs are not obtainable for a hackathon demo — **this must be disclosed as synthetic data in the pitch, not presented as real historical near-miss records**, consistent with the project's own "No Fabrication" principle already stated for the ML models

New endpoint `/api/patterns/query`: given a current or historical `AccidentPath`, retrieve structurally similar past incidents and surface the common precursor pattern. This is what feeds Agent 2 (Incident Pattern Agent, §4.2).

### 6.3 Change Required

| Component | Change |
|---|---|
| Regulatory RAG service | Add second FAISS index (`incidents_index`) alongside existing `regulatory_index` — same service, same embedding pipeline, separate index namespace |
| New endpoint | `/api/patterns/query` (analogous to existing `/api/query`) |
| Corpus | Curate ~30-50 incident summaries (public sources + synthetic near-miss reports schema-matched to `AccidentPath`) |
| `AccidentPath` | Add optional `similar_incidents: List[IncidentReference]` field populated by Agent 2 |

### 6.4 Effort

Low-medium. Reuses 100% of existing RAG infrastructure (FAISS, embedding pipeline, Gemini generation, `/api/verify`-style endpoint pattern). The bottleneck is corpus curation, which is a data-collection task, not an engineering task.

---

## 7. G5 — Emergency Response: Approval-Gated Only → Agent-Drafted, Still Approval-Gated

Covered structurally in §4.2 (Agent 1). Restated here as its own gap because it maps to a distinctly named deliverable ("Emergency Response Orchestrator — reducing the critical first 10 minutes from chaos to coordinated response").

### 7.1 Current State

`/risk/approve` requires a `safety_manager`-or-above role to approve a `CutRecommendation` before any intervention is logged as actioned. There is no drafted evacuation/alert/incident-report artifact — the operator sees the recommendation (e.g., "close barrier B-3, evacuate zone-1, suspend permit HW-007") but must manually compose alerts and the incident report.

### 7.2 Goal State

On a `CutRecommendation` crossing a severity threshold, Agent 1 automatically produces:
1. A per-channel alert draft (SMS text, PA announcement script, dashboard banner text) referencing the specific zones and hazard
2. An evacuation checklist ordered by zone risk (`R_i(t)` descending) and propagation timing (`estimate_time_to_harm()` output, which the pipeline already computes in Stage 9 and currently under-uses downstream)
3. A DGMS/OISD-formatted preliminary incident report skeleton, pre-filled with the `[M]`/`[P]`/`[C]` event chain, timestamped and hash-chain-referenced to the audit log entry that will be created on approval

None of this executes automatically. The safety_manager reviews the draft alongside the existing `CutRecommendation` and approves or edits before anything is sent or logged as actioned. This preserves the existing fail-closed, human-gated design while directly answering the "first 10 minutes" framing in the problem statement — the claim becomes "we cut the drafting and composition time to near-zero," which is both true and honestly scoped, rather than "we autonomously evacuate the plant," which would be both false and a bad safety design.

### 7.3 Effort

Low, once Agent 1 (§4) exists — this section is Agent 1's primary output, not separate work.

---

## 8. G6 — Barrier State: Binary Status → Live Barrier Health

### 8.1 Current State

`barrier_status` is one of the eleven `SafetyEvent` types — a barrier is reported as up/down at a point in time. `barrier_down()` is one of the composable predicates. This is sufficient for the current rule-evaluation logic but does not capture *degradation short of failure*, which is the specific insight that distinguishes "Live Barrier Health" (§ industry research, Enablon/SmartQHSE) from simple up/down status: <br>a barrier rarely fails outright — it drifts via bypassed interlocks, overdue proof tests, or excessive demand counts, and catching that drift early is the entire value proposition of dynamic barrier management over static bow-tie documentation.

### 8.2 Goal State

`Barrier` node gains fields beyond binary status:
- `last_proof_test: datetime`
- `proof_test_interval: timedelta` (from the source bow-tie's performance standard)
- `bypass_active: bool`
- `demand_count_since_test: int`
- `health_status: Literal["healthy", "degraded", "impaired"]` — derived, not directly set, computed from the above

`barrier_down()` predicate becomes `barrier_health_below(threshold)`, generalizing the existing binary check without breaking any existing rule definitions (a `health_status == "impaired"` check is backward-compatible with the old binary `barrier_down()` semantics).

This directly enables a **Cumulative Risk Heat Map**-equivalent to what Enablon's Dynamic Bowtie product offers commercially — multiple simultaneously-degraded barriers on the same top event compound risk even before any single one is fully "down," which the current binary model cannot represent.

### 8.3 Effort

Medium. This is a genuine schema and rule-engine extension, not a relabeling — `barrier_health_below()` needs new evaluation logic, and the CP-SAT cut optimizer's cost model should ideally weight "restore a degraded barrier" as a cheaper, lower-latency intervention option than "close/isolate," which the optimizer does not currently have as an action type.

---

## 9. G7, G8, G9 — Lower-Priority Items

**G7 (Continuous compliance scorecard):** Structurally identical to Agent 3 in §4.2. Low marginal cost once the RAG dual-corpus (G4) and agent orchestrator (G2) exist — this is a scheduling and aggregation task over existing `/api/verify` calls, not new retrieval infrastructure.

**G8 (Vision pipeline):** YOLOv8m and ByteTrack currently report `inference_mode="degraded"` because they need torch. Two honest options for a hackathon: (a) get a CPU-feasible path working (YOLOv8n, not m, at reduced accuracy, sufficient for a live demo on limited hardware) and clearly state the accuracy tradeoff, or (b) leave it degraded and do not claim CCTV/vision capability in the pitch beyond "designed for, not yet load-bearing in this demo." Claiming a working vision pipeline that is actually returning `degraded_reason` in a live demo is a credibility risk if a judge inspects the Models view, which explicitly surfaces `inference_mode`.

**G9 (Forecasting):** Already scoped in the source project document §4.1 (Prophet/SARIMA). No change to this document's assessment — the existing plan (forecasted events enter as `information_class="P"` and flow through the unchanged pipeline) is architecturally sound and requires no revision. Sequencing note: this is lower priority than G1-G6 for the hackathon because it does not address any currently-zero deliverable in the problem statement, whereas G1-G6 do.

---

## 10. Consolidated Data Model Changes

Summary of every schema addition specified above, for implementation reference:

```
CandidateIntervention:
  + barrier_role: Literal["preventive", "mitigative"]

AccidentPath:
  + top_event: str
  + similar_incidents: List[IncidentReference]   # populated by Agent 2

BowTie (new):
  hazard_id, top_event, threats, preventive_barriers,
  mitigative_barriers, consequences, source_reference

Barrier (extends existing barrier node):
  + last_proof_test: datetime
  + proof_test_interval: timedelta
  + bypass_active: bool
  + demand_count_since_test: int
  + health_status: Literal["healthy","degraded","impaired"]  # derived

SpatialZone (new):
  zone_id, polygon_points: List[Point2D], image_ref,
  scale_reference: Optional[float], scale_confidence: Literal["calibrated","assumed"]

IncidentReference (new):
  incident_id, source, similarity_score, summary
```

No existing field is removed or renamed in a breaking way. Every change is additive to preserve the existing 28-test-module suite and the 26 scenario fixtures without requiring a parallel rewrite of test infrastructure.

---

## 11. Sequencing Plan for Hackathon Timeframe

Given a compressed build window, recommended order:

**Phase 1 (highest leverage, lowest cost):**
1. G1 — bow-tie relabeling and `source_reference`/`barrier_role` fields (schema-only, no logic change)
2. G3 — geospatial overlay, since Blueprint Canvas and the risk propagator already exist; this is primarily a frontend rendering change plus one new table

**Phase 2 (new but bounded infrastructure):**
3. G4 — incident RAG corpus (reuses 100% of existing RAG service code)
4. G2, Agent 1 only — response drafting (highest-visibility agentic component for the demo, directly answers "Emergency Response Orchestrator")

**Phase 3 (if time remains):**
5. G2, Agents 2-3 — pattern mining and compliance scorecard
6. G6 — live barrier health
7. G8 — vision pipeline CPU path, only if a working demo is achievable; otherwise state as roadmap

**Explicitly deferred, state as roadmap in the pitch:** G9 (forecasting) — already well-specified in the existing project document and does not need re-litigating here; correctly scoped as future work.

---

## 12. What Not to Change

For completeness and to avoid scope creep during implementation: the following components are correctly designed as-is and should not be touched.

- **MinimumCausalCutOptimiser (CP-SAT hitting-set formulation)** — this is the project's strongest, most defensible technical differentiator relative to every commercial competitor surveyed (Enablon, SmartQHSE, Sphera, Yokogawa ProSafe-RS) — none of them automatically solves for a minimum-cost intervention set; they visualize barrier status and let a human decide. Do not weaken this into an LLM-suggested action list under pressure to "make it more agentic" — the deterministic optimality guarantee is the point.
- **Fail-closed pipeline design (Stage 1-5)** — halting on validation/state-projection failure rather than computing a cut on partial state is correct and should be preserved through every change above; the new agent orchestrator is explicitly designed (§4.3) to sit outside this critical path for exactly this reason.
- **Information Classification Framework (M/P/S/C/R/H)** — this is already the correct abstraction for every new data source introduced above (synthetic incident corpus tagged `[S]`, forecasted events tagged `[P]`, uncalibrated blueprint coordinates tagged `[S]`). Extend its use; do not introduce a parallel tagging scheme.
- **Human-in-the-loop approval gateway and hash-chained audit log** — every new agentic capability (G2, G5) is designed to feed this gate, not bypass it.

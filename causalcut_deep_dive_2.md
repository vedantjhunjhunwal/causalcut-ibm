# CAUSALCUT — Technical Deep Dive (Round 2)

---

## Q2 — ADWIN and Gas Sensor Drift: The Real Mechanics

### What is sensor drift?

A gas sensor is a chemical transducer — it converts molecular concentration into voltage. Over time, the sensing material (metal oxide, electrochemical cell) physically degrades:
- The catalyst surface gets fouled or poisoned
- Temperature/humidity-induced baseline shift
- Reference electrode degradation

The result: the sensor starts reporting 150 ppm when the actual concentration is 100 ppm. This is **drift** — a systematic, slow, time-correlated bias. It is not a gas spike. If you treat drift as a real alert, you'll desensitize operators ("cry wolf effect"). If you ignore it, a drifting sensor masks real leaks.

### How ADWIN detects it

**ADWIN (ADaptive WINdowing)** is a streaming change detection algorithm from the concept-drift literature. Here is the exact mechanism:

1. Maintain a sliding window $W$ of recent sensor readings (e.g., last 1000 readings).
2. At every new reading, ADWIN tests whether any contiguous subwindow of $W$ has a statistically different mean from the rest. Formally it tests:
   
$$\left| \mu_{W_0} - \mu_{W_1} \right| \geq \varepsilon_{\text{cut}}$$

where $\varepsilon_{\text{cut}} = \sqrt{\frac{1}{2m} \cdot \ln\frac{4n}{\delta}}$, with $m = |W_0| + |W_1|$, $n$ = total observations, and $\delta$ = confidence parameter.

3. If the condition is satisfied, a distributional shift is confirmed. ADWIN then **shrinks the window** to only include post-change data, effectively "forgetting" the old regime.

### What it means for CAUSALCUT specifically

- **No drift detected:** Readings are stable around baseline. XGBoost's gas-type predictions carry normal confidence. Events tagged `information_class=MEASURED`.
- **Drift detected:** The event's `drift_flag=True` is set. The uncertainty field is bumped to `1.0`. The Pydantic model emits a `GAS_ANOMALY` event with a high-uncertainty tag. Downstream, the CompoundRuleEngine's `rising_gas()` predicate still fires if the concentration exceeds threshold — but the hyperedge condition carries `InformationClass.MEASURED` at low confidence, meaning the risk engine knows this evidence is questionable.

**The key insight:** ADWIN doesn't prevent alerts — it *qualifies* them. A drifting sensor can still see a real spike. ADWIN flags the evidence quality so the operator gets context: "Warning: gas exceeded threshold, but sensor GS-03 has been drifting for the last 6 hours — confidence is low."

---

## Q4 — PPE Auto-Detection: What the Schema Actually Supports (and the Fix)

### What's currently broken (precisely)

Looking at the `Scenario` schema, there are two PPE input paths:

**Path A — Manual declaration** (what you've been using):
```json
"workers": [{"worker_id": "W-001", "zone_id": "zone-1", "missing_ppe": ["hard_hat"]}]
```
This bypasses vision entirely. Workers are manually declared with their PPE status.

**Path B — Vision pipeline** (exists in schema, needs wiring):
```json
"vision_inputs": [{"zone_id": "zone-1", "image_b64": "<base64>", "image_id": "frame-0"}]
```
The `VisionInput` schema accepts a base64-encoded image or an image reference. `generate_model_events()` is supposed to run YOLO inference on this and emit `PPE_VIOLATION` / `WORKER_PRESENCE` events automatically. **This path exists architecturally but the YOLO model service needs to be running and responding.**

### The correct architecture for auto-preloading

The fix is a **pre-scenario image inference step** before the scenario runs. Here is the proposed flow:

1. User uploads image(s) to a new endpoint: `POST /api/v1/vision/detect`
2. YOLO + ByteTrack runs on the image(s), returns detections: `{worker_id (track_id), zone_id, ppe_status, bbox}`
3. The frontend **pre-populates the workers array** in the scenario JSON from these detections
4. The scenario submits with real worker IDs and real PPE flags — no manual entry

The `TrackingInput` schema already supports passing bounding boxes + track IDs directly:
```json
"tracking_inputs": [{"zone_id": "zone-1", "detections": [{"frame_id": 0, "bbox": [x,y,w,h], "class": "person", "confidence": 0.91}]}]
```

ByteTrack assigns persistent `track_id` values across frames. These become `W-{track_id}` worker IDs automatically. This is the gap to close — the schema is ready, the wiring between vision service output and scenario builder pre-fill is missing.

---

## Q5 — Permit Validation Gap: Filling the Missing Rule

You are exactly right — it's predicate logic. Rules are evaluated periodically and when new events arrive. The gap I identified (no `HE-PERMIT-CONFLICT` rule) is real and here is what to add to [`compound_rules.py`](file:///c:/Users/Niranjan/Desktop/THE%20HYD%20PROJECT/et-ai-hackathon/app/engine/compound_rules.py):

**Incompatible permit types:** Hot work + confined space entry in the same zone simultaneously. Hot work creates ignition sources; confined space entry means a worker is physically enclosed and cannot rapidly exit. Together they represent a trapped-worker-in-ignition-zone scenario.

The new rule needs a `multi_permit_conflict()` predicate that:
1. Queries all active permits in a zone: `g.active_permits_in_zone(zone_id)`
2. Checks if the set contains both `hot_work` and `confined_space_entry`
3. Returns `satisfied=True` if the conflict exists, with `information_class=SYNTHETIC` (permits are synthetic data)

A second gap: **permit expiry vs. current conditions.** If a permit was issued when gas was safe but conditions have since changed, the rule should fire. This needs a timestamp comparison — permit `issued_at` vs. current `last_gas_ppm` — which is implementable once permits carry an `issued_at` attribute.

---

## Q6 — Dynamic Compound Rules: LLM Agent + RL Feasibility

### LLM-based rule authoring (feasible now)

Your architecture is exactly right. The system engineer describes an incident in natural language. An LLM agent (e.g., Gemini) parses it and generates a new `CompoundRule` Python object. The flow:

1. Engineer inputs: *"We had a situation where a valve failed while workers were doing maintenance in the hydraulic zone and the fire suppression was offline for testing. The combination caused a hydraulic oil spray fire."*

2. LLM agent extracts the causal structure:
   - **Mandatory:** `equipment_failing` (valve) 
   - **Contributing:** `barrier_down("fire_suppression")`, `active_permit("maintenance")`, `worker_present()`
   - **Pathway:** `hydraulic_fire`
   - **Top event:** "Hydraulic oil spray ignition during maintenance with suppression offline"
   - **Source reference:** "Incident INC-2024-031"

3. LLM generates a `CompoundRule` dataclass with the right predicate functions, OISD citations, severity function.

4. A human engineer reviews and approves (same gateway pattern as interventions).

5. The rule is persisted to a `compound_rules_db.json` and loaded at startup alongside the hardcoded defaults.

**Feasibility:** High. The predicate vocabulary is small and fixed (6 predicate builders in `compound_rules.py`). The LLM doesn't need to generate arbitrary code — it selects from the vocabulary and configures parameters. This is prompt engineering, not fine-tuning. You can constrain the LLM output to a JSON schema that maps directly to `CompoundRule` fields.

### Reinforcement Learning for hazard detection (research findings)

**The core problem:** RL is a sequential decision-making framework. An agent observes state, takes actions, receives rewards, and updates policy. For compound rule *discovery* (what you're describing), you'd need:

- **State:** Current plant sensor readings (gas ppm, equipment condition, ventilation, PPE, permits)
- **Action:** "Declare this combination a hazard" or "Don't"  
- **Reward:** +1 if a declared hazard was confirmed by a real incident, -1 if it was a false alarm, -10 for a missed real hazard

**The fundamental problem is reward sparsity.** Industrial accidents are rare by design. An RL agent learning in a real plant would receive a meaningful reward signal only when an accident occurs — which could take years of operation. This makes vanilla RL completely infeasible for rule discovery in this domain.

**What has been researched (viable alternatives):**

| Approach | Mechanism | Feasibility |
|----------|-----------|-------------|
| **Imitation Learning from safety engineers** | The LLM agent watches engineers annotate past incidents, learns the predicate-selection pattern | High — this is essentially supervised learning on structured outputs |
| **Causal Discovery (PC Algorithm, NOTEARS)** | Learns a directed acyclic graph from observational data, finds which variables causally precede incidents | Medium — requires labeled incident data which is rare |
| **Offline RL on incident databases** | Learn a policy from OSHA's 300k+ incident records without needing live plant interaction | Medium — OSHA data lacks the fine-grained sensor readings needed |
| **Model-based RL with a plant simulator** | Train RL agent against SimPy simulation, transfer to real plant | Low-Medium — transfer gap is enormous; simulated physics don't capture all failure modes |
| **LLM-as-policy with RLHF** | Use Gemini as the rule-generating policy, train with human engineer feedback | High — essentially your LLM agent idea formalized as RLHF |

**Verdict:** Pure RL for rule discovery is currently not feasible because the reward signal is too sparse and too expensive (real accidents). The LLM agent + human approval path (your Q6 architecture) is the correct near-term approach. If you want learning, implement it as **RLHF**: use the LLM as the policy, engineer feedback as the reward signal, and fine-tune over time. This is technically sound and implementable.

---

## Q7 — Propagation Parameters: Origin, Definition, and Update Path

All parameters are in [`topology.py`](file:///c:/Users/Niranjan/Desktop/THE%20HYD%20PROJECT/et-ai-hackathon/app/engine/topology.py) and [`risk_propagator.py`](file:///c:/Users/Niranjan/Desktop/THE%20HYD%20PROJECT/et-ai-hackathon/app/engine/risk_propagator.py). Here is every parameter, its current origin, and how it should be updated:

| Parameter | Current Value | Source | Should Be Updated By |
|-----------|--------------|--------|----------------------|
| `w_ij` (edge weight Zone-1 → Zone-4) | `0.65` | Engineering estimate | Plant HVAC drawings; CFD simulation of gas diffusion |
| `w_ij` (Zone-1 → Zone-2 doorway) | `0.25` | Engineering estimate | Physical measurement of air exchange rate |
| `λ_i` Zone-1 decay rate | `0.004/s` | Placeholder | Ventilation airflow measurements; 250 ppm CO decays to safe in ~40 min |
| `λ_i` Zone-4 decay rate | `0.015/s` | Placeholder | Higher because extraction fans are in Zone-4 |
| `κ` coupling rate | `0.02/s` | Stability constraint (`dt × κ < 0.2`) | Kept fixed for numerical stability; tune `w_ij` instead |
| `B_ij` barrier multiplier | `1.0` (default = open) | Fail-open assumption | Updated live from `BARRIER_STATUS` events — if a gas isolation valve closes, `B_ij → 0.0` |
| `S_i` injection coefficient | `0.03` | Calibrated guess | Should be fit to OSHA severity → time curves |
| `θ` harm threshold | `0.75` | Design choice | Calibrate against "time-to-first-casualty" distributions from historical incidents |

**The update mechanism that exists:** `B_ij` is already dynamic — the `CounterfactualSimulator` mutates `barrier_multiplier` mid-simulation when a `close_barrier` intervention is applied. The `scenario_runner.py` passes `barrier_multiplier={}` (all barriers open) as the initial condition — meaning **barrier status from the live graph is not yet feeding the propagation model**. That's a gap.

**What the `_MEDIUM_WEIGHT` dict in `scenario_runner.py` does:** When running a scenario (not using the hardcoded Steelforge topology), zone adjacency weights are derived from the medium type declared in the scenario JSON — `ventilation_duct → 0.6`, `utility_bus → 0.3`, `doorway → 0.25`. These override the static `topology.py` values, making the propagation scenario-specific.

---

## Q8 — Hardcoded Interventions + RL-based Policy: Feasibility Research

### Current state

Yes, interventions are fully hardcoded in `_candidate_interventions()`. The 7 action types are: suspend permit, evacuate worker, trip equipment, increase ventilation, enforce PPE, gas isolation, close zone. These are the interventions the authors knew about. A plant engineer likely knows 50 more (e.g., "switch to nitrogen purge", "reroute process gas to flare", "lock out electrical panel EL-04").

### SOP-based intervention ingestion (your Q8 idea)

This is directly implementable. The architecture:

1. Engineer uploads Standard Operating Procedures as text documents.
2. An LLM agent parses each SOP and extracts `(trigger_condition → action_steps)` pairs.
3. Each action step becomes a `CandidateIntervention` template with:
   - `action`: the SOP action text (e.g., "Open nitrogen purge valve NPV-03")
   - `breaks_factors`: LLM-inferred from the SOP description (e.g., `{"gas_source"}`)
   - `cost_category`: inferred from SOP priority
   - `execution_time_min`: from SOP timing specifications
4. These templates are stored in a database and loaded into `_candidate_interventions()` at runtime alongside the hardcoded ones.

**Feasibility:** High. SOPs are structured documents with clear condition → action mappings. An LLM excels at this extraction. The only hard part is the `breaks_factors` inference — you need to map action descriptions to the fixed vocabulary (`gas_source`, `ignition_source`, etc.). With a constrained output prompt, this is achievable.

### RL for intervention policy (research findings)

**The setting you described is formally a Partially Observable Markov Decision Process (POMDP):**
- **State:** Full plant condition (partially observed through sensors)
- **Action:** Choose intervention from candidate set
- **Reward:** Risk reduction achieved
- **Transition:** How the plant responds to the intervention (physics)

**Why this is actually more feasible than Q6's RL:**

Unlike rule discovery (where reward is sparse because accidents are rare), intervention RL can use the **SimPy counterfactual simulator as the environment**. The agent:
1. Observes current risk state
2. Selects an intervention
3. SimPy simulates the intervention
4. Agent receives `risk_reduction` as reward

This is **model-based offline RL** using the physics simulator as the environment — no real accidents required. The RL agent learns which interventions work best in which situations, potentially discovering non-obvious combinations (e.g., "boosting ventilation before suspending hot work is more effective than the reverse").

**Challenges:**
- **Sim-to-real gap:** The SimPy Euler diffusion is a simplification. An RL agent that learns to exploit simulation artifacts may not generalize to the real plant.
- **Discrete action space:** CP-SAT already finds the exact optimal combinatorial solution in milliseconds for the current scale. RL would only win if the action space grew too large for exact solvers (thousands of interventions).
- **Safety during exploration:** RL needs to explore suboptimal actions to learn. In a safety-critical domain, this is unacceptable in production. Offline RL (training only on historical data) avoids this but requires a large dataset.

**Verdict:** RL for intervention selection is feasible as a **research direction** on top of the existing SimPy simulator. For the current scope, CP-SAT finds the provably optimal answer and RL adds complexity without improving correctness. Where RL wins: **prioritization under uncertainty** — when the simulator can't fully model the plant, an RL agent trained on real plant response data would learn the residual dynamics that physics can't capture. The correct sequence is: CP-SAT now → collect real intervention outcome data → train offline RL policy → A/B test against CP-SAT.

---

## Q9 — The `0.8` and `0.2` Parameters: Yes, Hardcoded

```python
residual = base * (0.8 * open_fraction + 0.2 * hazard_fraction)
```

**Yes, these are hardcoded design choices in `cut_optimiser.py`.** The meaning:

- `0.8` weight on `open_fraction`: 80% of residual risk comes from accident routes that are still causally open. If half the routes are broken, residual risk drops by ~40%.
- `0.2` weight on `hazard_fraction`: 20% of residual risk is a "background hazard" penalty — even if all routes are broken (workers evacuated, permits suspended), a gas source still in the plant can seed new routes as conditions change. This prevents the system from reporting `residual_risk = 0.0` when there's still an active gas leak.

**Are they calibrated?** No. They are engineering judgment. The correct approach to calibrate these would be:
1. Run the simulator with known interventions against scenarios where the true outcome is known.
2. Fit the coefficients by minimizing `MSE(predicted_residual_risk, actual_harm_observed)`.
3. The OSHA incident database with time-to-harm and intervention records could serve as the calibration set.

**The broader problem** you've identified is real: mapping combinatorial covering to a probability is philosophically hard. What the formula actually computes is not a rigorous probability — it's a **dimensionless risk score** that monotonically decreases as more routes are broken. The safety community uses "risk index" or "risk number" for exactly this reason, avoiding the word "probability." A proper Bayesian approach would maintain a posterior over plant state and update it after each intervention, but that's a full probabilistic graphical model — beyond this project's scope.

---

## Q10 — BM25 Hybrid Search: Implementation Plan

You're right that pure semantic search misses exact regulatory clause references. Example: a query for "OISD-105 section 7.3" will fail semantically if the clause text doesn't overlap well with the query embedding. BM25 (Best Match 25) is a TF-IDF variant that scores documents on term frequency with saturation — it excels at exact term matching.

### What to implement

**Hybrid retrieval with Reciprocal Rank Fusion (RRF):**

1. **BM25 component:** Index all regulatory text chunks with `rank-bm25` (Python library, pure BM25 implementation). At query time, BM25 scores all chunks by term overlap.
2. **FAISS component:** Existing cosine similarity over `multi-qa-MiniLM-L6-cos-v1` embeddings (already built).
3. **RRF fusion:** Combine rankings: `score_rrf(d) = 1/(k + rank_bm25(d)) + 1/(k + rank_faiss(d))`, where `k=60` is the RRF constant that dampens the impact of very high vs. very low ranks.

**Why RRF instead of weighted scores:** Weighted linear combination requires calibrating the relative scale of BM25 scores (unbounded integers) and cosine scores (bounded [-1,1]). RRF uses only rank positions, making it scale-invariant and robust.

**Files to modify in `regulatory_rag/`:**
- `vector_store.py` — add `query_bm25()` method alongside existing `search()`
- `vector_store.py` — add `query_hybrid()` that fuses BM25 + FAISS results via RRF
- `config.py` — add `BM25_K1=1.5`, `BM25_B=0.75`, `RRF_K=60` constants
- `api.py` — expose `?mode=hybrid|semantic|keyword` query parameter

---

## Separate — LSTMs/GRUs vs LightGBM: The Full Picture

### What "regulatory interpretability" means

OSHA and DGMS regulations require that safety decisions be **explicable** to regulators and in post-incident investigations. Consider this scenario: a worker was injured, and CAUSALCUT had predicted failure_probability=0.73 for LATHE-01. A regulator asks: *"Why did your system say the lathe was failing?"*

With **LightGBM:** You can answer: *"Tool wear contributed 38% to the prediction, rotational speed deviation 27%, temperature gradient 19%. At the time, tool wear was at 220 minutes (normal: <80), which is the dominant factor."* This is a legal audit trail.

With **LSTM:** The prediction comes from 256 hidden state dimensions that encode temporal dynamics across the last 30 timesteps. You can compute attention weights or SHAP values, but the explanation becomes: *"The pattern of recent readings over the last 5 minutes matches patterns the model learned from similar failures."* This is harder to defend in a regulatory hearing, though not impossible (SHAP for LSTMs exists).

### The case for a hybrid ensemble

Your instinct is correct. Here is the principled architecture:

**Tiered approach:**

| Component | What it captures | Technology |
|-----------|-----------------|------------|
| **Snapshot model** | Current instantaneous state — features at time T | LightGBM (fast, explainable, regulatory-safe) |
| **Temporal model** | Degradation trajectory — rate of change, trend, cycles since last maintenance | LSTM or Temporal Convolutional Network (TCN) |
| **Ensemble combiner** | Weighted average where the temporal model gets higher weight when history is long | Calibrated logistic regression or learned gate |

**TCN vs LSTM:** Temporal Convolutional Networks use dilated causal convolutions to capture long-range dependencies without the vanishing gradient problem. They train faster than LSTMs on industrial data and are easier to deploy (no hidden state to maintain between calls). For this project, TCN would be the recommended upgrade from LightGBM if you go the temporal route.

**When temporality actually matters:** The NASA C-MAPSS dataset (already used) is specifically designed for this. Engine degradation follows a clear temporal trajectory — early, middle, and late life have different sensor signatures that a snapshot model can't distinguish without the temporal context. An LSTM trained on C-MAPSS with a rolling 30-cycle window would meaningfully outperform LightGBM on RUL estimation. For the AI4I failure mode classification (snapshot data), the gain is smaller.

**Regulatory compliance with temporal models:** Use SHAP with the background distribution set to "healthy baseline" readings. The explanation becomes: *"Compared to the healthy baseline of this machine type, the temporal model identified an accelerating torque anomaly over the last 47 cycles that matches a known bearing wear signature."* This is defensible.


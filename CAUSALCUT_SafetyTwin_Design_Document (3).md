# CAUSALCUT — Minimum-Causal-Cut Safety Twin

## Virtual Factory Layout & Complete Technical Architecture
### Steelforge Industries

**Document Version:** 1.0  
**Date:** July 2026  
**Classification:** Competition-Grade MVP Design  
**Target Build Window:** 15 Days

---

# 1. SYSTEM NAME AND THESIS

## 1.1 Name

**CAUSALCUT** — **C**ausal **A**ccident-path **U**ncovering **S**ystem with **A**utomated **L**east-**CUT** Intervention

**Full Form:** Causal Accident-path Uncovering System with Automated Least-Cut Intervention for Industrial Safety

## 1.2 Architectural Thesis

CAUSALCUT is the first safety-operations system that models a live industrial plant as a **dynamic safety hypergraph**, extracts **developing multi-domain accident chains** in real time, and computes the **minimum-cardinality causal cut** — the smallest operationally feasible set of interventions that provably breaks every high-risk accident path below a configurable safety threshold — subject to regulatory, feasibility, cost, and human-approval constraints, while maintaining strict separation between measured observations, model predictions, synthetic assumptions, counterfactual estimates, regulatory evidence, and human decisions.

## 1.3 Tagline

> *"Not what went wrong — what to cut, right now, to keep everyone safe."*

---

# 2. REDESIGNED VIRTUAL FACTORY LAYOUT

## 2.1 Physical Topology — Steelforge Industries

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                    STEELFORGE INDUSTRIES — CAUSALCUT SAFETY TWIN               ║
║                         Virtual Factory Floor Plan                              ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                 ║
║  ┌─────────────────────────┐    ┌─────────────────────────┐                     ║
║  │  ZONE 1: COKE OVEN      │    │  ZONE 2: BLAST FURNACE  │                     ║
║  │  Gas Hazard Zone         │    │  High-Risk Process Zone  │                     ║
║  │                          │    │                          │                     ║
║  │  [S] GS-01..GS-16       │    │  [S] GS-17..GS-32       │                     ║
║  │  (16 gas sensors)        │    │  (16 gas sensors, higher │                     ║
║  │                          │    │   baseline thresholds)   │                     ║
║  │  [S] TEMP-01..TEMP-04    │    │  [S] TEMP-05..TEMP-08   │                     ║
║  │  [S] VENT-01 (airflow)   │    │  [S] VENT-02 (airflow)  │                     ║
║  │                          │    │                          │                     ║
║  │  [M] CAM-01, CAM-02     │    │  [M] CAM-03, CAM-04     │                     ║
║  │  (CCTV + PPE detection)  │    │  (CCTV + PPE detection)  │                     ║
║  │                          │    │                          │                     ║
║  │  Workers: W-001..W-005   │    │  Workers: W-006..W-010   │                     ║
║  │  Permits: Hot Work,      │    │  Permits: Hot Work,      │                     ║
║  │    Confined Space        │    │    Electrical Isolation   │                     ║
║  │                          │    │                          │                     ║
║  │  ◄─── EMERGENCY EXIT E1  │    │  ◄─── EMERGENCY EXIT E2  │                     ║
║  │                          │    │                          │                     ║
║  │  [B] Fire Suppression    │    │  [B] Fire Suppression    │                     ║
║  │  [B] Gas Isolation Valve │    │  [B] Gas Isolation Valve │                     ║
║  └────────────┬─────────────┘    └─────────────┬────────────┘                     ║
║               │                                 │                                 ║
║               │   ╔═══════════════════════╗     │                                 ║
║               │   ║  HAZARD PROPAGATION   ║     │                                 ║
║               ├───║  CORRIDOR (gas duct,  ║─────┤                                 ║
║               │   ║  ventilation trunk,   ║     │                                 ║
║               │   ║  shared utilities)    ║     │                                 ║
║               │   ╚═══════════╤═══════════╝     │                                 ║
║               │               │                  │                                 ║
║  ┌────────────┴───────────────┴──────────────────┴────────────┐                   ║
║  │              ZONE 4: SHARED UTILITIES                       │                   ║
║  │              Ventilation & Emergency Isolation Zone          │                   ║
║  │                                                             │                   ║
║  │  [S] VENT-MAIN (central extraction fan RPM, flow)          │                   ║
║  │  [S] PRESS-01..PRESS-06 (duct pressure sensors)            │                   ║
║  │  [S] ELEC-ISO-01..ELEC-ISO-04 (isolation switch states)   │                   ║
║  │  [S] MECH-ISO-01..MECH-ISO-03 (mechanical lockouts)       │                   ║
║  │                                                             │                   ║
║  │  [B] Emergency Shutdown Panel (ESD-01)                     │                   ║
║  │  [B] Ventilation Override Controls                          │                   ║
║  │  [B] Fire Water Deluge Valves (FW-01..FW-03)              │                   ║
║  │  [B] Utility Isolation Manifold                             │                   ║
║  │                                                             │                   ║
║  │  ═══ Steam Header ═══  ═══ Compressed Air ═══             │                   ║
║  │  ═══ Cooling Water  ═══  ═══ Electrical Bus ═══            │                   ║
║  │                                                             │                   ║
║  │  ◄─── EMERGENCY EXIT E5 (to MUSTER POINT MP-2)            │                   ║
║  └───────────┬────────────────────────────┬────────────────────┘                   ║
║              │                             │                                       ║
║  ┌───────────┴────────────┐  ┌─────────────┴──────────────────┐                   ║
║  │  ZONE 3: MACHINE SHOP  │  │  ZONE 5: SITE-WIDE CCTV /     │                   ║
║  │  Rotating Equipment     │  │  PPE Checkpoints               │                   ║
║  │                         │  │                                 │                   ║
║  │  Assets:                │  │  [M] CAM-05..CAM-10            │                   ║
║  │   LATHE-01 (L-type)     │  │  (Entry/exit checkpoints at    │                   ║
║  │   MILL-01  (M-type)     │  │   Zone 1, 2, 3 boundaries)    │                   ║
║  │   DRILL-01 (H-type)     │  │                                 │                   ║
║  │   PUMP-HYD-01           │  │  PPE Detection Models:         │                   ║
║  │   PUMP-HYD-02           │  │   - Hard hat                   │                   ║
║  │                         │  │   - Safety vest                 │                   ║
║  │  [S] Air temp, Process  │  │   - Safety goggles             │                   ║
║  │      temp, RPM, Torque  │  │   - Gloves                     │                   ║
║  │      Tool wear          │  │                                 │                   ║
║  │  [S] Hydraulic: PS1-6,  │  │  Worker Tracking:              │                   ║
║  │      FS1-2, TS1-4,      │  │   Location, Zone, PPE status  │                   ║
║  │      VS1, EPS1          │  │   Entry/Exit timestamps        │                   ║
║  │                         │  │                                 │                   ║
║  │  Permits: Mechanical,   │  │  ◄─── EMERGENCY EXIT E4        │                   ║
║  │    LOTO                 │  │  ◄─── MUSTER POINT MP-1        │                   ║
║  │                         │  │                                 │                   ║
║  │  [B] Machine Guards     │  └─────────────────────────────────┘                   ║
║  │  [B] LOTO Lockboxes     │                                                       ║
║  │                         │                                                       ║
║  │  Workers: W-011..W-015  │                                                       ║
║  │  ◄─── EMERGENCY EXIT E3 │                                                       ║
║  └─────────────────────────┘                                                       ║
║                                                                                     ║
║  ┌───────────────────────────────────────────────────────────────────────────────┐   ║
║  │                    ZONE 6: CONTROL ROOM                                       │   ║
║  │                    Permit & Shift Management (Admin, Non-Hazard)              │   ║
║  │                                                                               │   ║
║  │  CAUSALCUT OPERATOR CONSOLE                                                   │   ║
║  │  ┌─────────────────────────────────────────────────────────────────────────┐  │   ║
║  │  │  LIVE SAFETY HYPERGRAPH VIEW    │  MINIMUM-CAUSAL-CUT PANEL           │  │   ║
║  │  │  ─ All zones, sensors, workers  │  ─ Active accident paths            │  │   ║
║  │  │  ─ Risk heatmap overlay         │  ─ Candidate interventions          │  │   ║
║  │  │  ─ Barrier status               │  ─ Risk before / after              │  │   ║
║  │  │  ─ Propagation arrows           │  ─ [APPROVE] [REJECT] [DEFER]      │  │   ║
║  │  ├─────────────────────────────────┼─────────────────────────────────────┤  │   ║
║  │  │  TIME-TO-HARM TIMELINE          │  PERMIT VALIDATION                  │  │   ║
║  │  │  ─ Predicted escalation curve   │  ─ Active permits vs. conditions    │  │   ║
║  │  │  ─ Intervention deadlines       │  ─ Conflicts & violations           │  │   ║
║  │  │  ─ Uncertainty bands            │  ─ Shift handover status            │  │   ║
║  │  └─────────────────────────────────┴─────────────────────────────────────┘  │   ║
║  │                                                                               │   ║
║  │  [S] Synthetic permit-to-work logs (aligned to sensor spikes)                │   ║
║  │  [S] Synthetic shift changeover logs                                          │   ║
║  │  [R] RAG Corpus: OISD Standards, Factories Act 1948, DGMS Circulars         │   ║
║  │  [M] OSHA historical incident data (offline calibration)                     │   ║
║  │                                                                               │   ║
║  │  Shift Officers: SO-A, SO-B, SO-C                                            │   ║
║  │  Safety Manager: SM-01                                                        │   ║
║  └───────────────────────────────────────────────────────────────────────────────┘   ║
║                                                                                     ║
║  ═══════════════════════════════════════════════════════════════════════════════     ║
║  MUSTER POINTS: MP-1 (South Gate)  MP-2 (East Gate)  MP-3 (North Gate)            ║
║  EVACUATION ROUTES: E1→MP-3  E2→MP-3  E3→MP-1  E4→MP-1  E5→MP-2                 ║
║  ═══════════════════════════════════════════════════════════════════════════════     ║
╚══════════════════════════════════════════════════════════════════════════════════╝
```

### 2.2 Visual Language Key

| Symbol | Meaning |
|--------|---------|
| Red solid line ──── | High-risk accident path (measured/validated) |
| Orange dashed line - - - | Uncertain or partially observed path |
| Green ◆ | Intervention / causal-cut point |
| Blue ■ [B] | Active safety barrier |
| Grey ░ | Failed, unavailable, or stale component |
| [S] | Sensor element |
| [M] | Monitoring element (camera) |

### 2.3 Information Class Tags

| Tag | Meaning |
|-----|---------|
| **[M]** | Measured observation — directly from sensor or camera |
| **[P]** | Model prediction — output of trained ML model |
| **[S]** | Synthetic assumption — generated identity/timestamp/relationship |
| **[C]** | Counterfactual estimate — "what-if" simulation result |
| **[R]** | Regulatory evidence — from RAG over OISD/DGMS/Factories Act |
| **[H]** | Human decision — operator approval or rejection |

### 2.4 Minimum-Causal-Cut Overlay

```
ACCIDENT PATH EXAMPLE (Coke Oven Scenario):

  [M] GS-03 rising      [S] PTW-007 active     [M] CAM-01: W-003
  (Ammonia > 200ppm)     (hot work permit,       (no hard hat
       │                  Zone 1)                 detected)
       │                      │                       │
       ▼                      ▼                       ▼
  ┌─────────────────────────────────────────────────────────┐
  │          COMPOUND HYPEREDGE HE-042                       │
  │  Rising toxic gas + Active hot-work + Missing PPE        │
  │  + Ventilation degradation [P] + Worker in zone [M]      │
  │                                                           │
  │  → PATHWAY: Toxic exposure / Flash fire                  │
  │  → TIME-TO-HARM: ~8 minutes [P] (±3 min uncertainty)    │
  │  → SEVERITY: CRITICAL                                    │
  └──────────────────────┬──────────────────────────────────┘
                         │
          CANDIDATE INTERVENTIONS:
          ┌──────────────────────────────────────────┐
          │ ◆ Suspend PTW-007     (cost: LOW)  [C]   │
          │ ◆ Evacuate W-003     (cost: LOW)  [C]   │
          │ ◆ Increase VENT-01   (cost: MED)  [C]   │
          │ ◆ Close Zone 1       (cost: HIGH) [C]   │
          │ ◆ Require PPE        (cost: LOW)  [C]   │
          └──────────────────────────────────────────┘
                         │
          MINIMUM CAUSAL CUT (selected):
          ╔══════════════════════════════════════════╗
          ║ 1. Suspend PTW-007         [C] → [H]    ║
          ║ 2. Evacuate W-003          [C] → [H]    ║
          ║                                          ║
          ║ Residual Risk: 0.08 (threshold: 0.15)   ║
          ║ Cost: LOW | Disruption: MINIMAL          ║
          ║ Status: AWAITING HUMAN APPROVAL          ║
          ╚══════════════════════════════════════════╝
```

### 2.5 Zone 4 Justification

Zone 4 (Shared Utilities, Ventilation & Emergency Isolation) is added because:

1. **Hazard propagation medium**: Gas, heat, and electrical faults travel through shared ventilation ducts, steam headers, and electrical buses between Zones 1, 2, and 3.
2. **Intervention leverage**: Emergency shutdowns, ventilation overrides, and utility isolation are the highest-leverage intervention points that affect multiple zones simultaneously.
3. **Failure cascade source**: A ventilation failure in Zone 4 can simultaneously degrade conditions in Zones 1 and 2, creating compound risk that single-zone models cannot detect.
4. **Data source**: The Hydraulic Condition Monitoring dataset (UCI #447) provides multi-sensor time-series (pressure, flow, temperature, vibration) that naturally maps to utility monitoring with its 17 physical sensors and 4 fault types.

---

# 3. COMPLETE TECHNICAL ARCHITECTURE

## 3.1 System Architecture Diagram

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║                        CAUSALCUT — SYSTEM ARCHITECTURE                       ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  DATA SOURCES (Stateless, Async)                                             ║
║  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          ║
║  │Gas Sensor│ │Equip.    │ │CCTV/PPE  │ │Permit/   │ │Incident/ │          ║
║  │Arrays    │ │Telemetry │ │Feeds     │ │Shift Logs│ │Regulatory│          ║
║  │(UCI×2)   │ │(AI4I,Hyd,│ │(SH17,    │ │(Synthetic│ │(OSHA,    │          ║
║  │          │ │Azure,NASA│ │Roboflow) │ │Generated)│ │OISD,DGMS)│          ║
║  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘          ║
║       │             │            │             │             │                ║
║  ─────┼─────────────┼────────────┼─────────────┼─────────────┼──── TRUST ──  ║
║       │             │            │             │             │    BOUNDARY   ║
║       ▼             ▼            ▼             ▼             ▼                ║
║  ┌───────────────────────────────────────────────────────────────────────┐    ║
║  │  INGESTION & VALIDATION LAYER (Stateless, Sync)                      │    ║
║  │  ─ Schema validation (Pydantic)                                      │    ║
║  │  ─ Deduplication (event_id + hash)                                   │    ║
║  │  ─ Out-of-order handling (validity_window)                           │    ║
║  │  ─ Stale-data flagging                                               │    ║
║  │  ─ Information-class tagging ([M], [P], [S], [C], [R], [H])         │    ║
║  └───────────────────────────────────┬───────────────────────────────────┘    ║
║                                      │                                        ║
║                                      ▼                                        ║
║  ┌───────────────────────────────────────────────────────────────────────┐    ║
║  │  ASYNC EVENT QUEUE (Stateful — SQLite WAL / PostgreSQL)              │    ║
║  │  ─ In-process asyncio.Queue (MVP) → PostgreSQL LISTEN/NOTIFY (prod) │    ║
║  │  ─ Dead-letter table for failed processing                           │    ║
║  │  ─ Idempotent consumers with event_id dedup                          │    ║
║  └───────────────────────────────────┬───────────────────────────────────┘    ║
║                                      │                                        ║
║       ┌──────────────────────────────┼────────────────────────────┐           ║
║       ▼                              ▼                            ▼           ║
║  ┌──────────┐  ┌──────────────┐  ┌──────────┐  ┌──────────────┐             ║
║  │GAS       │  │EQUIPMENT     │  │PPE/WORKER│  │PERMIT/SHIFT  │             ║
║  │ANOMALY   │  │FAILURE       │  │PRESENCE  │  │VALIDATION    │             ║
║  │MODULE    │  │PREDICTION    │  │DETECTION │  │MODULE        │             ║
║  │(Offline  │  │MODULE        │  │MODULE    │  │(Stateless)   │             ║
║  │trained)  │  │(Offline      │  │(Offline  │  │              │             ║
║  │          │  │trained)      │  │trained)  │  │              │             ║
║  │XGBoost + │  │LightGBM +   │  │YOLOv8 +  │  │Rule engine + │             ║
║  │drift det.│  │survival      │  │tracking  │  │conflict det. │             ║
║  │          │  │analysis      │  │          │  │              │             ║
║  └────┬─────┘  └──────┬───────┘  └────┬─────┘  └──────┬───────┘             ║
║       │               │               │               │                      ║
║       ▼               ▼               ▼               ▼                      ║
║  ┌───────────────────────────────────────────────────────────────────────┐    ║
║  │  CANONICAL SAFETY EVENT EMITTER (Stateless)                          │    ║
║  │  ─ Normalizes all module outputs to canonical event schema           │    ║
║  │  ─ Assigns event_id, confidence, uncertainty, provenance             │    ║
║  │  ─ Tags information_class and synthetic_flag                         │    ║
║  └───────────────────────────────────┬───────────────────────────────────┘    ║
║                                      │                                        ║
║                    ┌─────────────────┼─────────────────┐                     ║
║                    ▼                 ▼                  ▼                     ║
║  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐       ║
║  │  EVENT STORE     │  │  PLANT-STATE     │  │  DYNAMIC SAFETY     │       ║
║  │  (Append-only,   │  │  STORE           │  │  HYPERGRAPH         │       ║
║  │  Stateful)       │  │  (Stateful,      │  │  (Stateful,         │       ║
║  │                  │  │  materialized    │  │  in-memory           │       ║
║  │  SQLite/Postgres │  │  view)           │  │  NetworkX)           │       ║
║  │  + Audit log     │  │                  │  │                      │       ║
║  └──────────────────┘  │  Current state   │  │  Nodes: workers,     │       ║
║                        │  of every zone,  │  │  assets, zones,      │       ║
║                        │  sensor, worker, │  │  sensors, hazards    │       ║
║                        │  asset, permit,  │  │                      │       ║
║                        │  barrier         │  │  Edges: pairwise     │       ║
║                        └────────┬─────────┘  │  Hyperedges: compound│       ║
║                                 │            │  danger conditions    │       ║
║                                 │            └──────────┬───────────┘       ║
║                                 │                       │                    ║
║                                 └───────────┬───────────┘                    ║
║                                             │                                ║
║                                             ▼                                ║
║  ┌───────────────────────────────────────────────────────────────────────┐    ║
║  │  COMPOUND-RISK DETECTION ENGINE (Stateful)                           │    ║
║  │  ─ Scans hypergraph for activated hyperedges                         │    ║
║  │  ─ Evaluates compound conditions (gas + permit + PPE + ventilation)  │    ║
║  │  ─ Applies historical incident calibration (OSHA patterns)           │    ║
║  └───────────────────────────────────┬───────────────────────────────────┘    ║
║                                      │                                        ║
║                                      ▼                                        ║
║  ┌───────────────────────────────────────────────────────────────────────┐    ║
║  │  SPATIOTEMPORAL RISK PROPAGATION (Stateful)                          │    ║
║  │  ─ Models how risk spreads across zones via shared utilities         │    ║
║  │  ─ Uses plant topology graph (Zone 4 connections)                    │    ║
║  │  ─ Weighted by gas diffusion rates, ventilation flow, barriers       │    ║
║  └───────────────────────────────────┬───────────────────────────────────┘    ║
║                                      │                                        ║
║                                      ▼                                        ║
║  ┌───────────────────────────────────────────────────────────────────────┐    ║
║  │  TIME-TO-HARM ESTIMATOR (Stateless)                                  │    ║
║  │  ─ Regression model: current conditions → estimated minutes to harm  │    ║
║  │  ─ Calibrated against OSHA severe-injury time patterns               │    ║
║  │  ─ Outputs point estimate + uncertainty interval                     │    ║
║  └───────────────────────────────────┬───────────────────────────────────┘    ║
║                                      │                                        ║
║                                      ▼                                        ║
║  ┌───────────────────────────────────────────────────────────────────────┐    ║
║  │  COUNTERFACTUAL SIMULATOR (Stateless per call, uses SimPy)           │    ║
║  │  ─ For each candidate intervention: simulate plant state change      │    ║
║  │  ─ Estimate residual risk, cost, disruption, execution time          │    ║
║  │  ─ Test action combinations                                          │    ║
║  │  ─ Mark all outputs as [C] counterfactual                            │    ║
║  └───────────────────────────────────┬───────────────────────────────────┘    ║
║                                      │                                        ║
║                                      ▼                                        ║
║  ┌───────────────────────────────────────────────────────────────────────┐    ║
║  │  MINIMUM-CAUSAL-CUT OPTIMISER (Stateless, OR-Tools)                  │    ║
║  │  ─ Input: active accident paths + candidate interventions            │    ║
║  │  ─ Objective: minimize total cost while breaking all critical paths  │    ║
║  │  ─ Constraints: feasibility, regulatory, compatibility, approval     │    ║
║  │  ─ Output: smallest intervention set + residual risk                 │    ║
║  └───────────────────────────────────┬───────────────────────────────────┘    ║
║                                      │                                        ║
║                   ┌──────────────────┼──────────────────┐                    ║
║                   ▼                                     ▼                    ║
║  ┌──────────────────────┐           ┌──────────────────────────────────┐     ║
║  │  REGULATORY VERIFIER │           │  LLM EXPLANATION LAYER           │     ║
║  │  (Stateless)         │           │  (Stateless)                     │     ║
║  │                      │           │                                  │     ║
║  │  FAISS index over    │           │  Converts validated cut +        │     ║
║  │  OISD/DGMS/Factories │           │  regulatory evidence into        │     ║
║  │  Act text chunks     │           │  operator-readable summary       │     ║
║  │                      │           │                                  │     ║
║  │  Validates: is the   │           │  LLM does NOT calculate risk,    │     ║
║  │  proposed cut legal? │           │  select interventions, or        │     ║
║  └──────────┬───────────┘           │  enforce regulations             │     ║
║             │                       └────────────┬─────────────────────┘     ║
║             └───────────────┬────────────────────┘                           ║
║                             ▼                                                ║
║  ┌───────────────────────────────────────────────────────────────────────┐    ║
║  │  HUMAN APPROVAL GATEWAY (Stateful)                                   │    ║
║  │  ─ Presents recommendation to authorized operator                    │    ║
║  │  ─ Shows: risk before/after, cost, regulatory basis, uncertainty     │    ║
║  │  ─ Requires: [APPROVE] [REJECT] [DEFER] with reason                 │    ║
║  │  ─ Logs decision with timestamp, approver_id, correlation_id        │    ║
║  │  ─ NO automatic action without human approval                        │    ║
║  └───────────────────────────────────┬───────────────────────────────────┘    ║
║                                      │                                        ║
║                                      ▼                                        ║
║  ┌───────────────────────────────────────────────────────────────────────┐    ║
║  │  OPERATIONAL REQUEST DISPATCHER (Stateful)                           │    ║
║  │  ─ Dispatches approved interventions as operational requests         │    ║
║  │  ─ Tracks execution status                                           │    ║
║  │  ─ Collects outcome feedback                                         │    ║
║  └───────────────────────────────────┬───────────────────────────────────┘    ║
║                                      │                                        ║
║                                      ▼                                        ║
║  ┌───────────────────────────────────────────────────────────────────────┐    ║
║  │  OUTCOME FEEDBACK & RECALIBRATION (Offline)                          │    ║
║  │  ─ Did the intervention reduce risk as predicted?                    │    ║
║  │  ─ Update model confidence calibration                               │    ║
║  │  ─ Update counterfactual accuracy estimates                          │    ║
║  │  ─ Feed back into training pipeline                                  │    ║
║  └───────────────────────────────────────────────────────────────────────┘    ║
║                                                                               ║
║  ════════════════════════════════════════════════════════════════════════     ║
║  MONITORING SIDECAR (runs alongside all components):                        ║
║  ─ Logs (structured JSON), Metrics (Prometheus format), Traces (corr. ID)  ║
║  ─ Sensor-drift detection, Model-drift detection, Data-quality scoring     ║
║  ─ Stale-data alerts, Component health checks                               ║
║  ════════════════════════════════════════════════════════════════════════     ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

---

# 4. COMPONENT SPECIFICATIONS

## 4.1 Gas Anomaly & Sensor-Drift Detection Module

| Attribute | Specification |
|-----------|--------------|
| **Responsibility** | Classify gas type, detect concentration anomalies, identify sensor drift |
| **Input** | 128-dim feature vectors (16 sensors × 8 features per sensor) from Gas Sensor Array Drift dataset; 19-col time series from Dynamic Gas Mixtures dataset |
| **Algorithm** | XGBoost classifier for gas type (6 classes); Isolation Forest for anomaly detection; ADWIN for drift detection; threshold-based alerting for concentration exceedances |
| **Output** | Canonical SafetyEvent: gas_type, concentration_estimate, anomaly_score, drift_flag, severity (0-1), confidence, uncertainty |
| **Storage** | Event Store (append-only), Plant-State Store (latest reading per sensor) |
| **Communication** | Async: reads from event queue, writes canonical events |
| **Latency Target** | < 500ms from sensor reading to event emission |
| **Scaling** | Horizontal: one instance per zone (MVP: single instance) |
| **Failure Fallback** | If model fails: fall back to deterministic threshold rules (gas > X ppm → alert); flag as degraded; increase uncertainty to 1.0 |
| **Security Boundary** | Internal only; no external API; reads validated sensor data only |
| **Observability** | Log every prediction with correlation_id; track prediction latency, drift score, anomaly rate |
| **MVP Technology** | Python, scikit-learn, XGBoost |
| **Production Evolution** | Online learning for drift compensation; edge deployment; real sensor integration |

## 4.2 Equipment Failure Prediction Module

| Attribute | Specification |
|-----------|--------------|
| **Responsibility** | Predict machine failure probability and failure mode; estimate remaining useful life (RUL) |
| **Input** | AI4I 2020 features (air temp, process temp, RPM, torque, tool wear, product type); Hydraulic system sensors (PS1-6, FS1-2, TS1-4, VS1, EPS1); NASA C-MAPSS engine degradation profiles |
| **Algorithm** | LightGBM multi-label classifier for failure mode (TWF, HDF, PWF, OSF, RNF); XGBoost regressor for RUL; multi-sensor condition classification for hydraulic (cooler, valve, pump, accumulator) |
| **Output** | Canonical SafetyEvent: asset_id, failure_probability, failure_mode, RUL_estimate, component_condition, severity, confidence |
| **Storage** | Event Store; Plant-State Store (per-asset condition vector) |
| **Communication** | Async event processing |
| **Latency Target** | < 1s for real-time inference; RUL updated every 60s cycle |
| **Scaling** | Per-asset instance (MVP: single batch) |
| **Failure Fallback** | If model unavailable: use last known condition + increase uncertainty; trigger precautionary maintenance alert after 2× missed cycles |
| **Security Boundary** | Internal; asset data only |
| **Observability** | Track prediction accuracy vs. actual failures; log feature importance drift |
| **MVP Technology** | Python, LightGBM, scikit-learn |
| **Production Evolution** | Streaming inference; real SCADA integration; physics-informed models |

## 4.3 PPE & Worker-Presence Detection Module

| Attribute | Specification |
|-----------|--------------|
| **Responsibility** | Detect workers, classify PPE compliance (hard hat, vest, goggles), track zone presence |
| **Input** | Camera frames from SH17 dataset annotations; Hard-Hat Workers (Roboflow) bounding boxes |
| **Algorithm** | YOLOv8-nano for object detection (person, hard_hat, no_hard_hat, vest, no_vest); ByteTrack for worker tracking across frames; zone assignment by camera-to-zone mapping |
| **Output** | Canonical SafetyEvent: worker_id (synthetic), zone_id, ppe_status (dict), detection_confidence, frame_timestamp |
| **Storage** | Event Store; Plant-State Store (per-worker current location + PPE) |
| **Communication** | Async; processes frames at 2-5 FPS (MVP: batch over sample images) |
| **Latency Target** | < 200ms per frame |
| **Scaling** | One inference worker per camera group |
| **Failure Fallback** | CCTV outage: flag zone as "unobserved", increase uncertainty for all workers last seen there, issue precautionary PPE-check alert |
| **Security Boundary** | Privacy-sensitive; no raw frames stored; only detection events |
| **Observability** | Track detection rate, false positive rate, camera uptime |
| **MVP Technology** | Python, ultralytics (YOLOv8), OpenCV |
| **Production Evolution** | Edge inference on NVIDIA Jetson; multi-camera fusion; face-anonymized audit trail |

## 4.4 Permit Validation Module

| Attribute | Specification |
|-----------|--------------|
| **Responsibility** | Validate active permits against current zone conditions; detect conflicts |
| **Input** | Synthetic permit-to-work records (generated to align with sensor spikes); current plant state from Plant-State Store |
| **Algorithm** | Rule engine: permit_type × zone_conditions → {valid, conflict, expired, conditions_violated}; conflict detection: multiple simultaneous permits in same zone with incompatible work types |
| **Output** | Canonical SafetyEvent: permit_id, validation_status, conflict_list, violated_conditions |
| **Storage** | Event Store; active permit registry in Plant-State Store |
| **Communication** | Synchronous check on permit state change; periodic re-validation every 60s |
| **Latency Target** | < 100ms per validation |
| **Failure Fallback** | If validation engine fails: flag all active permits as "unverified"; escalate to shift officer |
| **MVP Technology** | Python, rule-based logic |
| **Production Evolution** | Integration with real PTW systems; mobile permit approval |

## 4.5 Shift-Handover Inconsistency Detection

| Attribute | Specification |
|-----------|--------------|
| **Responsibility** | Detect inconsistencies during shift changeover (orphaned permits, unacknowledged hazards, incomplete handover checklists) |
| **Input** | Synthetic shift changeover logs; active permit registry; current plant state |
| **Algorithm** | Rule-based: compare outgoing shift state with incoming shift acknowledgment; flag unacknowledged hazards, unclosed permits, missing sign-offs |
| **Output** | Canonical SafetyEvent: shift_id, inconsistency_type, affected_permits, affected_zones |
| **Latency Target** | < 5s at shift boundary |
| **MVP Technology** | Python, rule-based logic |

## 4.6 Dynamic Safety Hypergraph Engine

| Attribute | Specification |
|-----------|--------------|
| **Responsibility** | Maintain real-time hypergraph of all plant entities and their relationships; identify activated compound-danger hyperedges |
| **Input** | All canonical safety events from all modules |
| **Algorithm** | NetworkX graph with custom hyperedge representation (hyperedge = frozenset of node IDs + activation conditions); activation check: for each hyperedge template, evaluate whether all constituent conditions are simultaneously true |
| **Output** | List of activated hyperedges with severity scores; accident-development paths (directed subgraphs) |
| **Storage** | In-memory NetworkX graph; snapshot to SQLite every 60s |
| **Communication** | Subscribes to all canonical events; publishes activated hyperedges |
| **Latency Target** | < 200ms for full graph evaluation |
| **Failure Fallback** | If graph evaluation fails: freeze last known state, flag as stale, switch to deterministic zone-level alerting |
| **MVP Technology** | Python, NetworkX |
| **Production Evolution** | Specialized hypergraph engine; GPU-accelerated graph traversal |

## 4.7 Counterfactual Simulator

| Attribute | Specification |
|-----------|--------------|
| **Responsibility** | Simulate the effect of candidate interventions on plant state and risk |
| **Input** | Current plant state; candidate intervention; plant topology |
| **Algorithm** | SimPy discrete-event simulation: clone current state → apply intervention → advance simulation 5-30 min → measure resulting risk; Monte Carlo with N=100 samples for uncertainty estimation |
| **Output** | CounterfactualResult: intervention_id, risk_before, risk_after, workers_protected, execution_time_estimate, cost_estimate, disruption_score, feasibility, uncertainty |
| **Latency Target** | < 3s for full counterfactual comparison of top-10 interventions |
| **Failure Fallback** | If simulator fails: use static lookup table of pre-computed intervention effects; flag as degraded estimate |
| **MVP Technology** | Python, SimPy |

## 4.8 Minimum-Causal-Cut Optimiser

| Attribute | Specification |
|-----------|--------------|
| **Responsibility** | Select the smallest set of interventions that breaks all critical accident paths below the safety threshold |
| **Input** | Active accident paths (from hypergraph); counterfactual results for each candidate intervention; constraints (regulatory, feasibility, compatibility, availability) |
| **Algorithm** | Weighted Set Cover formulation solved with OR-Tools CP-SAT solver (see Section 6 for formal formulation) |
| **Output** | InterventionRecommendation: ordered list of interventions, total cost, residual risk, required approver, regulatory basis |
| **Latency Target** | < 2s for typical problem size (≤50 paths, ≤20 interventions) |
| **Failure Fallback** | If optimiser fails: recommend pre-defined emergency protocol for the highest-severity zone; flag as "fallback recommendation" |
| **MVP Technology** | Python, OR-Tools |

## 4.9 Regulatory Verifier (RAG)

| Attribute | Specification |
|-----------|--------------|
| **Responsibility** | Retrieve relevant regulatory text for proposed interventions; verify compliance |
| **Input** | Proposed intervention set; zone context |
| **Algorithm** | FAISS vector index over chunked regulatory text (OISD standards, Factories Act 1948, DGMS circulars); cosine similarity retrieval of top-5 relevant chunks; rule-based compliance check against extracted requirements |
| **Output** | Regulatory evidence: relevant_clauses, compliance_status, required_actions |
| **Latency Target** | < 1s |
| **MVP Technology** | Python, FAISS, sentence-transformers |

---

# 5. DATA CONTRACTS

## 5.1 Canonical Event Schema

```json
{
  "event_id": "uuid-v4",
  "factory_id": "steelforge-001",
  "zone_id": "zone-1",
  "event_type": "gas_anomaly | equipment_failure | ppe_violation | permit_conflict | shift_inconsistency | barrier_status | compound_risk",
  "worker_id": "W-003 | null",
  "asset_id": "LATHE-01 | null",
  "event_time": "2026-07-11T10:30:00Z",
  "validity_window": "PT5M",
  "value": {"gas_type": "ammonia", "concentration_ppm": 215.4},
  "severity": 0.82,
  "confidence": 0.91,
  "uncertainty": 0.15,
  "source": "gas_anomaly_module_v2",
  "model_version": "xgb-gas-v2.1.0",
  "provenance": "UCI_GasSensorDrift_Batch7",
  "information_class": "M",
  "synthetic_flag": false,
  "schema_version": "1.0.0"
}
```

## 5.2 Plant State Schema

```json
{
  "state_id": "uuid-v4",
  "factory_id": "steelforge-001",
  "timestamp": "2026-07-11T10:30:00Z",
  "zones": {
    "zone-1": {
      "gas_readings": [{"sensor_id": "GS-01", "value": 215.4, "unit": "ppm", "info_class": "M"}],
      "temperature": {"value": 42.3, "unit": "C", "info_class": "M"},
      "ventilation_status": "degraded",
      "workers_present": ["W-001", "W-003"],
      "active_permits": ["PTW-007"],
      "barriers": {"fire_suppression": "active", "gas_isolation": "active"},
      "risk_score": 0.72,
      "risk_info_class": "P"
    }
  },
  "schema_version": "1.0.0"
}
```

## 5.3 Hypergraph Relationship Schema

```json
{
  "hyperedge_id": "HE-042",
  "constituent_nodes": ["W-003", "zone-1", "PTW-007", "GS-03", "VENT-01"],
  "conditions": [
    {"node": "GS-03", "predicate": "concentration > 200ppm", "satisfied": true, "info_class": "M"},
    {"node": "PTW-007", "predicate": "type == hot_work AND status == active", "satisfied": true, "info_class": "S"},
    {"node": "W-003", "predicate": "ppe.hard_hat == false", "satisfied": true, "info_class": "M"},
    {"node": "VENT-01", "predicate": "flow_rate < 0.6 * nominal", "satisfied": true, "info_class": "P"}
  ],
  "pathway": "toxic_exposure_or_flash_fire",
  "severity": 0.92,
  "activation_time": "2026-07-11T10:28:00Z",
  "synthetic_flag": false
}
```

## 5.4 Risk Forecast Schema

```json
{
  "forecast_id": "uuid-v4",
  "zone_id": "zone-1",
  "timestamp": "2026-07-11T10:30:00Z",
  "current_risk": 0.82,
  "predicted_risk_5min": 0.91,
  "predicted_risk_15min": 0.96,
  "time_to_harm_minutes": 8.2,
  "time_to_harm_uncertainty": 3.1,
  "confidence": 0.78,
  "active_pathways": ["HE-042", "HE-043"],
  "info_class": "P"
}
```

## 5.5 Counterfactual Result Schema

```json
{
  "counterfactual_id": "uuid-v4",
  "intervention_id": "INT-suspend-PTW007",
  "intervention_type": "suspend_permit",
  "target": "PTW-007",
  "risk_before": 0.82,
  "risk_after": 0.31,
  "risk_reduction": 0.51,
  "workers_protected": ["W-001", "W-003"],
  "assets_protected": [],
  "execution_time_minutes": 2,
  "cost_category": "LOW",
  "production_disruption": "MINIMAL",
  "feasibility": 0.95,
  "regulatory_status": "compliant",
  "uncertainty": 0.18,
  "info_class": "C",
  "simulation_samples": 100,
  "random_seed": 42
}
```

## 5.6 Intervention Recommendation Schema

```json
{
  "recommendation_id": "uuid-v4",
  "timestamp": "2026-07-11T10:30:15Z",
  "interventions": [
    {"intervention_id": "INT-suspend-PTW007", "priority": 1, "action": "Suspend hot-work permit PTW-007 in Zone 1"},
    {"intervention_id": "INT-evacuate-W003", "priority": 2, "action": "Evacuate worker W-003 from Zone 1"}
  ],
  "total_cost": "LOW",
  "residual_risk": 0.08,
  "safety_threshold": 0.15,
  "threshold_met": true,
  "pathways_broken": ["HE-042"],
  "regulatory_basis": ["OISD-STD-116 Clause 4.3", "Factories Act 1948 Section 41"],
  "required_approver_role": "shift_officer",
  "info_class": "C",
  "status": "PENDING_APPROVAL"
}
```

## 5.7 Human Approval Schema

```json
{
  "approval_id": "uuid-v4",
  "recommendation_id": "uuid-v4",
  "approver_id": "SO-A",
  "approver_role": "shift_officer",
  "decision": "APPROVE | REJECT | DEFER",
  "reason": "Concur with permit suspension; W-003 evacuation initiated",
  "timestamp": "2026-07-11T10:31:02Z",
  "info_class": "H"
}
```

## 5.8 Intervention Outcome Schema

```json
{
  "outcome_id": "uuid-v4",
  "recommendation_id": "uuid-v4",
  "approval_id": "uuid-v4",
  "executed_interventions": ["INT-suspend-PTW007", "INT-evacuate-W003"],
  "execution_start": "2026-07-11T10:31:05Z",
  "execution_end": "2026-07-11T10:33:20Z",
  "observed_risk_after": 0.11,
  "predicted_risk_after": 0.08,
  "prediction_error": 0.03,
  "incident_occurred": false,
  "info_class": "M"
}
```

---

# 6. MINIMUM-CAUSAL-CUT FORMULATION

## 6.1 Formal Objective

Given:
- A set of **active accident paths** P = {p₁, p₂, ..., pₖ}
- A set of **candidate interventions** I = {i₁, i₂, ..., iₙ}
- For each intervention iⱼ: a binary decision variable xⱼ ∈ {0, 1}
- A **coverage matrix** C where Cₚⱼ = 1 if intervention iⱼ breaks path pₚ
- Per-intervention estimates: cost(iⱼ), disruption(iⱼ), execution_time(iⱼ), risk_reduction(iⱼ), uncertainty(iⱼ)

**Minimize:**

```
Σⱼ [ w_cost · cost(iⱼ) · xⱼ
    + w_disruption · disruption(iⱼ) · xⱼ
    + w_latency · execution_time(iⱼ) · xⱼ
    + w_uncertainty · uncertainty(iⱼ) · xⱼ ]
+ w_cardinality · Σⱼ xⱼ
```

**Subject to:**

1. **Path coverage**: For every critical path pₚ: Σⱼ Cₚⱼ · xⱼ ≥ 1 (every critical path must be broken by at least one selected intervention)

2. **Residual risk bound**: residual_risk(x) ≤ θ_safety (configurable threshold, default 0.15)

3. **Regulatory compliance**: For all j where xⱼ = 1: regulatory_status(iⱼ) ≠ "prohibited"

4. **Feasibility**: For all j where xⱼ = 1: feasibility(iⱼ) ≥ θ_feasibility (default 0.5)

5. **Compatibility**: For all incompatible pairs (iⱼ, iₖ): xⱼ + xₖ ≤ 1

6. **Availability**: For all j where xⱼ = 1: available(iⱼ) = true

7. **Approval requirement**: Human approval is mandatory before execution (not a solver constraint — enforced by the gateway)

## 6.2 OR-Tools Mapping

```python
from ortools.sat.python import cp_model

model = cp_model.CpModel()

# Decision variables: select intervention j?
x = [model.NewBoolVar(f'intervention_{j}') for j in range(n_interventions)]

# Constraint 1: Every critical path must be broken
for p in range(n_paths):
    model.Add(sum(coverage[p][j] * x[j] for j in range(n_interventions)) >= 1)

# Constraint 2: Residual risk bound (linearized)
# residual_risk ≈ base_risk - Σⱼ risk_reduction[j] * x[j]
model.Add(
    base_risk_scaled - sum(risk_reduction_scaled[j] * x[j]
    for j in range(n_interventions)) <= threshold_scaled
)

# Constraint 3: Regulatory compliance (exclude prohibited)
for j in prohibited_interventions:
    model.Add(x[j] == 0)

# Constraint 4: Feasibility threshold
for j in range(n_interventions):
    if feasibility[j] < feasibility_threshold:
        model.Add(x[j] == 0)

# Constraint 5: Incompatible pairs
for (j, k) in incompatible_pairs:
    model.Add(x[j] + x[k] <= 1)

# Constraint 6: Availability
for j in unavailable_interventions:
    model.Add(x[j] == 0)

# Objective: weighted sum
model.Minimize(
    sum(
        w_cost * cost_scaled[j] * x[j]
        + w_disruption * disruption_scaled[j] * x[j]
        + w_latency * latency_scaled[j] * x[j]
        + w_uncertainty * uncertainty_scaled[j] * x[j]
        for j in range(n_interventions)
    )
    + w_cardinality * sum(x[j] for j in range(n_interventions))
)

solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 2.0
status = solver.Solve(model)
```

Weight defaults: w_cost=1.0, w_disruption=2.0, w_latency=1.5, w_uncertainty=1.0, w_cardinality=3.0 (strongly prefer fewer interventions).

---

# 7. DATASET-TO-ARCHITECTURE MAPPING

## 7.1 Gas / Hazardous Atmosphere Datasets

| Dataset | Zone | Model | Key Features | Target | Generated Event | Confidence Method | Graph Role | Use | Limitation |
|---------|------|-------|-------------|--------|----------------|-------------------|------------|-----|------------|
| **UCI Gas Sensor Array Drift** (13,910 samples, 128 features) | Zone 1 (Coke Oven), Zone 2 (Blast Furnace — higher baseline) | XGBoost classifier + Isolation Forest | 128-dim: ΔR, normalized ΔR, EMA features × 16 sensors | Gas type (6 classes: Ethanol, Ethylene, Ammonia, Acetaldehyde, Acetone, Toluene) | `gas_anomaly` event with gas_type, anomaly_score | Cross-validated accuracy per batch; confidence = 1 - entropy of class probabilities | Sensor nodes, gas-condition nodes in hypergraph | **Online**: real-time classification; **Offline**: drift compensation training | No native timestamps; 36-month drift span must be used for drift modeling, not temporal ordering. Lab gases, not industrial. |
| **UCI Dynamic Gas Mixtures** (4.18M samples, 19 features) | Zone 1, Zone 2 | Reservoir computing / regression for concentration estimation | Time(s), gas concentrations (ppm), 16 sensor conductance channels | Ethylene + CO/Methane concentrations (ppm) | `gas_concentration` event with ppm estimates per gas | Regression RMSE on held-out time segments | Concentration nodes linked to zone and hazard nodes | **Offline**: train concentration regression; **Online**: continuous monitoring | 12-hour recordings; 100Hz sampling must be downsampled. Gas types limited. |
| **Kaggle Multimodal Gas Detection** | Zone 1, Zone 2 (supplementary) | Multi-modal fusion if image+sensor available | Sensor readings + optional spectrogram | Gas type classification | `gas_detection` event | Model-reported confidence | Supplementary sensor nodes | **Offline**: training augmentation | Verify feature compatibility; may not align with UCI schema. |

## 7.2 Predictive Maintenance Datasets

| Dataset | Zone | Model | Key Features | Target | Generated Event | Confidence Method | Graph Role | Use | Limitation |
|---------|------|-------|-------------|--------|----------------|-------------------|------------|-----|------------|
| **AI4I 2020 Predictive Maintenance** (10,000 samples, 6 features) | Zone 3 (Machine Shop) | LightGBM multi-label classifier | Air temp (K), Process temp (K), Rotational speed (rpm), Torque (Nm), Tool wear (min), Product type (L/M/H) | Machine failure (binary) + 5 failure modes (TWF, HDF, PWF, OSF, RNF) | `equipment_failure_prediction` event with failure_prob per mode | Cross-validated F1; probability calibration via Platt scaling | Asset nodes → failure-mode nodes → zone hazard nodes | **Online**: real-time failure prediction; **Offline**: model training | Synthetic dataset; no real timestamps; failure modes are deterministic rules. |
| **Azure Predictive Maintenance** | Zone 3 | Survival analysis + classification | Telemetry (voltage, rotation, pressure, vibration), errors, maintenance records, machine metadata | Failure within 24h (binary) + component ID | `equipment_degradation` event with RUL estimate | Time-dependent AUC | Asset lifecycle nodes | **Offline**: RUL model training; **Online**: degradation scoring | Multi-table schema requires join logic; timestamps are synthetic. |
| **NASA C-MAPSS** | Zone 3 (supplementary — turbofan → generalized rotating equipment) | LSTM / XGBoost regressor | 21 sensor readings per engine cycle; operational settings | Remaining Useful Life (cycles) | `rul_estimate` event | RMSE on test trajectories | Asset degradation trajectory nodes | **Offline**: RUL regression training | Turbofan-specific; transfer to general rotating equipment requires calibration. |
| **UCI Hydraulic Condition Monitoring** (2,205 cycles, 17 sensors, 43,680 features) | Zone 4 (Shared Utilities) — maps to utility pumps, coolers, accumulators | Multi-output classifier (cooler, valve, pump, accumulator condition) | PS1-6 (pressure), FS1-2 (flow), TS1-4 (temperature), VS1 (vibration), EPS1 (motor power), CE, CP, SE | Component condition grades (cooler: 3/20/100%; valve: 73-100%; pump: 0-2 leakage; accumulator: 90-130 bar) | `utility_condition` event with per-component health | Per-class accuracy; stable-flag validation | Utility nodes in Zone 4; connect to Zone 1-3 via shared services | **Online**: cycle-wise condition assessment; **Offline**: training | 60s fixed cycles; no failure events, only degradation levels. |

## 7.3 Vision / PPE Datasets

| Dataset | Zone | Model | Key Features | Target | Generated Event | Confidence Method | Graph Role | Use | Limitation |
|---------|------|-------|-------------|--------|----------------|-------------------|------------|-----|------------|
| **SH17 Dataset** | Zone 5 (checkpoints at Zone 1, 2, 3 entries) | YOLOv8-nano object detector | RGB images with bounding box annotations for safety equipment | 17 classes including hard hat, safety vest, person, various tools | `ppe_detection` event with worker_id (synthetic), ppe_items, zone_id | Detection confidence from YOLO; mAP on validation set | Worker-PPE nodes, worker-zone edges | **Offline**: model training; **Online**: frame-by-frame inference | Academic dataset; domain gap with real factory. |
| **Hard Hat Workers (Roboflow)** | Zone 5 | YOLOv8-nano (fine-tuned) | RGB images with bounding boxes | 3 classes: head, helmet, person | `ppe_hard_hat` event with hat_present boolean | Detection confidence | Worker-PPE subgraph | **Offline**: fine-tuning; **Online**: inference | Limited to hard hats only; must combine with SH17 for full PPE. |

## 7.4 Incident / Near-Miss / Geospatial

| Dataset | Zone | Model | Key Features | Target | Generated Event | Confidence Method | Graph Role | Use | Limitation |
|---------|------|-------|-------------|--------|----------------|-------------------|------------|-----|------------|
| **OSHA Severe Injury Reports** | Not zone-specific — used for calibration | Historical pattern extraction | Industry (SIC/NAICS), nature of injury, body part, event type, hospitalization/amputation/fatality | Injury severity and type distribution | N/A (offline calibration only) | Historical frequency analysis | Calibrates time-to-harm model and severity weights | **Offline**: prior distributions for time-to-harm; incident-type frequency | Reporting biases; US-specific; no sensor data. |
| **OSHA Accident Search** | Not zone-specific | Text pattern extraction | Free-text accident narratives, employer, location | Accident chain patterns | N/A (offline) | Manual validation of extracted patterns | Feeds accident-chain templates for hyperedge design | **Offline**: template extraction | Unstructured text; requires NLP parsing. |
| **Kaggle OSHA 2015-2017** | Not zone-specific | Statistical analysis | Structured accident records with industry, state, event type | Accident frequency by type | N/A (offline) | Statistical confidence intervals | Calibrates base rates for Bayesian risk estimation | **Offline**: base-rate calibration | Limited to 3 years; US steel industry subset is small. |

## 7.5 Regulatory (RAG Corpus)

| Source | Scope | Processing | Use |
|--------|-------|-----------|-----|
| **OISD Standards** | Plant-wide | Chunk into ~500-token passages; embed with sentence-transformers; index in FAISS | Regulatory evidence retrieval for intervention validation |
| **Factories Act 1948** | Plant-wide | PDF extraction; chunk; embed | Legal compliance verification |
| **DGMS Circulars** | Plant-wide (mines/hazardous industry) | Web scrape; chunk; embed | Supplementary regulatory context |

---

# 8. COMPLETE COKE-OVEN SCENARIO

## 8.1 Scenario Timeline

### T = 0:00 — Normal State

```
Zone 1 Status: GREEN
─ Gas sensors GS-01..GS-16: all within normal range [M]
─ Ventilation VENT-01: 100% capacity [M]
─ Workers: W-001 (shift lead), W-003 (operator) — both in Zone 1 [M]
─ PPE: W-001 (full compliance), W-003 (full compliance) [M]
─ Active Permits: PTW-007 (hot work, Zone 1, valid 06:00-14:00) [S]
─ Barriers: Fire suppression ACTIVE [M], Gas isolation ACTIVE [M]
─ Risk score: 0.12 [P] (below threshold 0.15)
```

### T = 3:00 — Rising Gas Detected

```
EVENT: gas_anomaly
─ GS-03 reads Ammonia concentration: 180 ppm (rising trend) [M]
─ GS-07 reads Ammonia concentration: 165 ppm [M]
─ Anomaly score: 0.71 (elevated but not critical) [P]
─ Sensor drift check: no drift detected [P]
─ Risk score: 0.38 [P]
─ Status: YELLOW — monitoring
```

### T = 5:30 — Hot-Work Permit Still Active

```
EVENT: permit_validation
─ PTW-007 (hot work) remains active in Zone 1 [S]
─ Condition check: gas concentration rising while hot work active [P]
─ CONFLICT DETECTED: Hot work + rising flammable/toxic gas [P]
─ Risk score: 0.55 [P]
```

### T = 6:00 — Worker PPE Violation Detected

```
EVENT: ppe_detection
─ CAM-01 detects W-003 in Zone 1: hard hat MISSING [M]
─ Detection confidence: 0.94 [M]
─ W-003 last PPE-compliant check: T = 2:00 [M]
─ Risk score: 0.62 [P]
```

### T = 7:00 — Ventilation Degradation Predicted

```
EVENT: utility_condition
─ VENT-01 airflow: 72% of nominal (declining) [M]
─ Zone 4 PRESS-02: duct pressure anomaly detected [M]
─ Predicted: VENT-01 will reach 50% capacity in ~10 min [P]
─ Confidence: 0.76 [P]
─ Risk score: 0.72 [P]
```

### T = 7:30 — Compound Hyperedge Activates

```
HYPEREDGE HE-042 ACTIVATED:
─ Constituent conditions:
  ├─ GS-03: Ammonia > 200 ppm (now 215 ppm) [M] ✓
  ├─ PTW-007: hot work active in Zone 1 [S] ✓
  ├─ W-003: hard hat missing [M] ✓
  ├─ VENT-01: flow < 60% nominal [P] ✓
  └─ W-003: present in Zone 1 [M] ✓

PATHWAY: Toxic exposure OR flash fire
SEVERITY: 0.92
```

### T = 7:45 — Accident Path Extracted

```
ACCIDENT DEVELOPMENT PATH:
  Rising gas [M]
    → Ventilation insufficient to clear [P]
      → Concentration will exceed IDLH in ~8 min [P]
        → Worker W-003 exposed without full PPE [M]
          → Hot work ignition source present [S]
            → POTENTIAL OUTCOME: Flash fire OR acute toxic exposure

RISK PROPAGATION:
  Zone 1 → Zone 2 (via shared ventilation duct in Zone 4) [P]
  Propagation probability: 0.35 (if VENT-01 fails further) [P]

TIME-TO-HARM ESTIMATE: 8.2 minutes [P] (±3.1 min uncertainty)
```

### T = 8:00 — Candidate Interventions Generated

```
COUNTERFACTUAL COMPARISON TABLE:

┌────────────────────────┬──────────┬──────────┬─────────┬───────────┬────────────┐
│ Intervention           │ Risk     │ Risk     │ Workers │ Cost      │ Disruption │
│                        │ Before   │ After    │ Saved   │           │            │
├────────────────────────┼──────────┼──────────┼─────────┼───────────┼────────────┤
│ Suspend PTW-007        │ 0.82     │ 0.48     │ 2       │ LOW       │ MINIMAL    │
│ Evacuate W-003         │ 0.82     │ 0.55     │ 1       │ LOW       │ LOW        │
│ Increase VENT-01 to    │ 0.82     │ 0.39     │ 2       │ MEDIUM    │ LOW        │
│   100% override        │          │          │         │           │            │
│ Close Zone 1           │ 0.82     │ 0.05     │ 2       │ HIGH      │ HIGH       │
│ Require W-003 PPE      │ 0.82     │ 0.71     │ 1       │ LOW       │ MINIMAL    │
│ Activate gas isolation  │ 0.82     │ 0.22     │ 2       │ MEDIUM    │ MEDIUM     │
│                        │          │          │         │           │            │
│ COMBINATION:           │          │          │         │           │            │
│ Suspend PTW-007 +      │ 0.82     │ 0.08     │ 2       │ LOW       │ MINIMAL    │
│ Evacuate W-003         │          │          │         │           │            │
└────────────────────────┴──────────┴──────────┴─────────┴───────────┴────────────┘

All values marked [C] — counterfactual estimates
```

### T = 8:05 — Minimum Causal Cut Selected

```
MINIMUM-CAUSAL-CUT SOLUTION:

  SELECTED INTERVENTIONS (cardinality = 2):
  ╔══════════════════════════════════════════════════════════════════╗
  ║ 1. SUSPEND PERMIT PTW-007 (hot work, Zone 1)                   ║
  ║    → Removes ignition source from accident path                ║
  ║    → Regulatory basis: OISD-STD-116 Cl. 4.3 [R]              ║
  ║    → Execution time: ~2 min                                    ║
  ║                                                                 ║
  ║ 2. EVACUATE WORKER W-003 FROM ZONE 1                          ║
  ║    → Removes exposed worker from toxic atmosphere              ║
  ║    → Regulatory basis: Factories Act 1948, Section 41 [R]     ║
  ║    → Execution time: ~3 min                                    ║
  ╠══════════════════════════════════════════════════════════════════╣
  ║ RISK BEFORE:  0.82 [P]                                        ║
  ║ RISK AFTER:   0.08 [C] (below threshold 0.15)                 ║
  ║ TOTAL COST:   LOW                                              ║
  ║ DISRUPTION:   MINIMAL                                          ║
  ║ UNCERTAINTY:  0.18 [C]                                         ║
  ║                                                                 ║
  ║ WHY NOT just "Require PPE"?                                    ║
  ║   → Alone: residual risk = 0.71 (above threshold)             ║
  ║   → Does not address gas + ignition source compound risk       ║
  ║                                                                 ║
  ║ WHY NOT "Close Zone 1"?                                        ║
  ║   → Achieves risk = 0.05 but at HIGH cost + HIGH disruption   ║
  ║   → The 2-intervention cut achieves threshold at lower cost    ║
  ║                                                                 ║
  ║ STATUS: AWAITING HUMAN APPROVAL                                ║
  ║ REQUIRED APPROVER: Shift Officer (SO-A or SO-B)               ║
  ╚══════════════════════════════════════════════════════════════════╝
```

### T = 8:10 — Human Approval

```
OPERATOR CONSOLE — SHIFT OFFICER SO-A:

  "Recommend suspending hot-work permit PTW-007 and evacuating
   worker W-003 from Zone 1. Ammonia concentration at 215 ppm
   and rising, ventilation degrading. This is the minimum action
   set to reduce risk below safety threshold."

  Regulatory Evidence:
   - OISD-STD-116 Clause 4.3: "Hot work shall be stopped
     immediately when hazardous atmosphere is detected" [R]
   - Factories Act 1948 Section 41: "No worker shall be required
     to work in conditions injurious to health" [R]

  [✓ APPROVE]  [ REJECT ]  [ DEFER ]

  SO-A Decision: APPROVE [H]
  Reason: "Concur. Notify W-001 (shift lead) to halt operations." [H]
  Timestamp: 2026-07-11T10:38:10Z
```

### T = 10:00 — Outcome Feedback

```
OUTCOME FEEDBACK:
─ PTW-007 suspended at T = 8:12 [M]
─ W-003 evacuated to MP-3 at T = 8:15 [M]
─ Gas concentration peaked at 242 ppm at T = 9:30, then declined [M]
─ VENT-01 restored to 85% at T = 12:00 after Zone 4 maintenance [M]
─ No incident occurred [M]
─ Observed risk after intervention: 0.11 [M]
─ Predicted risk after intervention: 0.08 [C]
─ Prediction error: 0.03 (within acceptable range)
─ FEEDBACK: Model calibration updated (+0.03 bias correction) [M]
```

---

# 9. MVP–PRODUCTION BOUNDARY

## 9.1 What Must Be Built Within 15 Days

| Component | MVP Scope | Status |
|-----------|----------|--------|
| Gas Anomaly Module | XGBoost classifier trained on UCI Drift dataset; threshold alerting | MUST BUILD |
| Equipment Failure Module | LightGBM on AI4I 2020; hydraulic condition classifier on UCI Hydraulic | MUST BUILD |
| PPE Detection Module | YOLOv8-nano fine-tuned on Hard Hat Workers; demo on sample images | MUST BUILD |
| Permit Validation | Rule engine with synthetic permits | MUST BUILD |
| Canonical Event Schema | Pydantic models for all event types | MUST BUILD |
| Plant-State Store | SQLite-backed materialized view | MUST BUILD |
| Dynamic Safety Hypergraph | NetworkX with 5-10 predefined hyperedge templates | MUST BUILD |
| Compound-Risk Detection | Hyperedge activation evaluation | MUST BUILD |
| Time-to-Harm Estimator | Regression model calibrated on OSHA time distributions | MUST BUILD |
| Counterfactual Simulator | SimPy-based with simplified plant model | MUST BUILD |
| Minimum-Causal-Cut Optimiser | OR-Tools CP-SAT with weighted set cover | MUST BUILD |
| Regulatory Verifier (RAG) | FAISS index over 50-100 regulatory text chunks | MUST BUILD |
| Human Approval Gateway | FastAPI endpoint + React approval UI | MUST BUILD |
| React Dashboard | Factory layout view, risk display, cut recommendation panel | MUST BUILD |
| Synthetic Scenario Engine | Generator for coke-oven scenario + 2-3 additional scenarios | MUST BUILD |
| Docker Compose | Single docker-compose.yml for all services | MUST BUILD |

## 9.2 What May Be Simplified or Simulated

| Component | Simplification |
|-----------|---------------|
| Real-time sensor streaming | Simulated via synthetic scenario playback |
| CCTV live inference | Batch inference over sample images, not live video |
| Worker tracking | Synthetic worker IDs and positions |
| Multi-zone propagation | Simplified adjacency-based model (not full CFD) |
| Shift handover | 2-3 predefined handover scenarios |
| LLM explanation | Template-based text generation (LLM optional) |
| Authentication/RBAC | Basic API key authentication |
| Outcome feedback loop | Manual trigger, not automated |

## 9.3 What Requires Real Plant Data

| Component | Requirement |
|-----------|------------|
| Gas sensor calibration | Real industrial sensor readings for field accuracy |
| Equipment models | SCADA/historian data from actual machines |
| PPE detection | Site-specific camera angles, lighting, PPE types |
| Permit integration | Real PTW system API |
| Plant topology | Actual P&ID drawings for propagation modeling |
| Regulatory corpus | Verified, current versions of OISD/DGMS standards |

## 9.4 What Requires Safety Validation / Certification

| Component | Requirement |
|-----------|------------|
| Minimum-Causal-Cut recommendations | Must NOT be used as sole decision basis without extensive validation |
| Time-to-harm estimates | Must be validated against real incident data before operational use |
| Automatic interventions | System must NEVER execute interventions without human approval |
| Regulatory compliance claims | Must be reviewed by certified safety engineers |
| Risk threshold values | Must be set by qualified process-safety engineers |
| Full system | Requires SIL (Safety Integrity Level) assessment per IEC 61511 before production deployment |

---

# APPENDIX A: SAFE FAILURE BEHAVIOUR MATRIX

| Failure Mode | Detection | Fallback | User Notification |
|-------------|-----------|---------|-------------------|
| Missing/stale sensor data | Validity window expiry check | Increase uncertainty to 1.0; use last known value; flag as stale | "⚠ Sensor GS-03 data stale (>5 min). Risk estimates degraded." |
| Sensor drift | ADWIN drift detector | Switch to drift-compensated model batch; increase uncertainty | "⚠ Sensor drift detected on GS-03. Accuracy may be reduced." |
| CCTV outage | Frame timeout (>10s) | Mark zone as "unobserved"; issue precautionary PPE alert for all workers last seen there | "⚠ Camera CAM-01 offline. Zone 1 PPE status unknown." |
| Model failure | Exception handling + timeout | Fall back to deterministic threshold rules; flag recommendations as "rule-based fallback" | "⚠ Gas classification model unavailable. Using threshold rules." |
| Database failure | Connection retry with backoff | Write to local WAL file; queue for replay; continue with in-memory state | "⚠ Database write delayed. Events buffered locally." |
| Queue failure | Dead-letter detection | Direct synchronous processing; reduced throughput | "⚠ Event queue degraded. Processing may be delayed." |
| Optimiser failure | Solver timeout (>2s) | Recommend pre-defined emergency protocol for highest-severity zone | "⚠ Optimiser timeout. Showing emergency protocol recommendation." |
| Regulatory retrieval failure | FAISS query timeout | Proceed without regulatory evidence; flag as "unverified" | "⚠ Regulatory lookup unavailable. Compliance not verified." |
| Conflicting predictions | Cross-module disagreement detection | Present both predictions with their confidence levels; escalate to human | "⚠ Gas and equipment models disagree on Zone 1 risk. Human review required." |
| Low-confidence forecast | Confidence < 0.5 | Widen uncertainty band; add "low confidence" warning; do NOT recommend automatic actions | "⚠ Low confidence forecast. Manual assessment recommended." |
| Missing worker identity | Detection without re-identification | Assign temporary ID; flag as "unidentified worker" | "⚠ Unidentified worker detected in Zone 1." |
| Network interruption | Heartbeat timeout | Local standalone mode; cache all events; sync when restored | "⚠ Network interrupted. Operating in standalone mode." |

---

# APPENDIX B: TECHNOLOGY STACK SUMMARY

| Layer | Technology | Justification |
|-------|-----------|--------------|
| Backend API | **FastAPI** (Python) | Async-native, fast, auto-docs, Pydantic validation |
| ML — Tabular | **scikit-learn, XGBoost, LightGBM** | Lightweight, fast training/inference, interpretable |
| ML — Vision | **PyTorch / ultralytics (YOLOv8)** | State-of-art object detection, nano variant for speed |
| Graph Engine | **NetworkX** | Pure Python, flexible, sufficient for MVP scale |
| Simulation | **SimPy** | Discrete-event simulation, Python-native, lightweight |
| Optimisation | **OR-Tools (CP-SAT)** | Google's constraint solver, fast for small-medium problems |
| Vector Search (RAG) | **FAISS** | Efficient similarity search, minimal dependencies |
| Database | **SQLite** (MVP) → **PostgreSQL** (production) | Zero-config for MVP; production-ready with Postgres |
| Frontend | **React** + **Plotly** | Interactive dashboards, real-time updates |
| Visualization | **Plotly / deck.gl** | Rich 2D/3D factory visualization |
| Containerization | **Docker** + docker-compose | Single-command deployment |

**Explicitly avoided**: Kafka (use asyncio queues), Kubernetes (use docker-compose), Neo4j (use NetworkX), Qdrant (use FAISS), unnecessary microservices (modular monolith).

**LLM usage constraint**: LLMs are used ONLY for (1) converting validated outputs into operator-readable text explanations, and (2) regulatory text retrieval assistance. LLMs do NOT calculate risk, generate accident paths, select interventions, enforce regulations, or control equipment.

---

**END OF DOCUMENT**

*CAUSALCUT — Steelforge Industries — Competition-Grade MVP Design*
*Document Version 1.0 — July 2026*

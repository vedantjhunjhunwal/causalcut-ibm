"""Scenario runner — the user-driven pipeline entrypoint.

Given a user-authored :class:`~app.schemas.scenario.Scenario`, this builds a
*fresh* ``SafetyHypergraph`` (deliberately NOT the hardcoded Steelforge
bootstrap), lowers the scenario to canonical events, feeds them through the
exact same analytical stack the live engine uses —

    compound rules -> accident paths -> minimum causal cut

— then adds risk propagation, time-to-harm, a baseline-vs-intervention
trajectory, regulatory verification (graceful-degrading), a plain-language
explanation, and a stable node/edge graph payload for the frontend.

Nothing here is scenario-specific hardcoding: every zone/sensor/worker/permit
comes from the submitted scenario.
"""

from __future__ import annotations

import logging
from typing import Any

import networkx as nx

from app.engine.compound_rules import CompoundRuleEngine
from app.engine.cut_optimiser import MinimumCausalCutOptimiser
from app.engine.hypergraph_wrapper import Relation, SafetyHypergraph
from app.engine.path_extractor import PathExtractor
from app.engine.risk_propagator import PropagationInputs, estimate_time_to_harm
from app.engine.types import NodeType
from app.schemas.scenario import Scenario
from app.simulation.counterfactual_sim import CounterfactualSimulator, Intervention

log = logging.getLogger("causalcut.scenario")

_PPM_SATURATION = 300.0
_MEDIUM_WEIGHT = {
    "ventilation_duct": 0.6,
    "shared_duct": 0.5,
    "shared_ventilation": 0.6,
    "utility_bus": 0.3,
    "utility_corridor": 0.3,
    "doorway": 0.25,
    "shared_utility": 0.3,
}


# --------------------------------------------------------------------------- #
# Graph construction
# --------------------------------------------------------------------------- #
def register_scenario_entities(scenario: Scenario) -> SafetyHypergraph:
    """Fresh graph with only the scenario's static topology registered.

    Events are applied separately: by the queue consumer in the production
    pipeline, or in-process by :func:`build_graph_from_scenario` for offline
    analysis and unit tests.
    """
    g = SafetyHypergraph(factory_id=scenario.factory_id)
    for z in scenario.zones:
        g.register_zone(z.zone_id, z.name, z.hazard_class, z.baseline_gas_threshold_ppm)
    for a in scenario.zone_adjacency:
        try:
            g.add_zone_adjacency(a.zone_a, a.zone_b, a.medium)
        except KeyError:
            pass
    for sn in scenario.sensors:
        g.register_sensor(sn.sensor_id, sn.zone_id, sn.modality, sn.unit)
    for asset in scenario.assets:
        g.register_asset(asset.asset_id, asset.zone_id, asset.asset_type)
    for w in scenario.workers:
        g.register_worker(w.worker_id, w.zone_id)
    for pm in scenario.permits:
        g.register_permit(pm.permit_id, pm.zone_id, pm.permit_type, pm.status, pm.worker_id)
    return g


def build_graph_from_scenario(scenario: Scenario, extra_events=None) -> SafetyHypergraph:
    """Register entities then apply events in-process (offline path)."""
    from app.engine.adapter import canonical_to_engine

    g = register_scenario_entities(scenario)
    for event in sorted(list(scenario.to_events()) + list(extra_events or []),
                        key=lambda e: e.event_time):
        ee = canonical_to_engine(event)
        if ee is not None:
            g.apply_event(ee)
    return g


def _scenario_topology(scenario: Scenario) -> nx.Graph:
    tg = nx.Graph()
    tg.add_nodes_from(z.zone_id for z in scenario.zones)
    for a in scenario.zone_adjacency:
        w = _MEDIUM_WEIGHT.get(a.medium, 0.3)
        tg.add_edge(a.zone_a, a.zone_b, weight=w, channel=a.medium)
    return tg


# --------------------------------------------------------------------------- #
# Regulatory verification (graceful-degrading)
# --------------------------------------------------------------------------- #
def verify_interventions(actions: list[str], zone_context: str,
                         correlation_id: str = "", scenario_id: str | None = None) -> dict[str, Any]:
    """Delegate to the shared RegulatoryModelService (real FAISS, else degraded).

    Model logic lives in ONE place; this is a thin adapter so the runner and
    the /models/regulatory/verify route behave identically.
    """
    from app.services.model_service import get_registry

    resp = get_registry().regulatory.verify(
        actions, zone_context, correlation_id=correlation_id, scenario_id=scenario_id)
    return {
        "citations": (resp.prediction or {}).get("citations", []),
        "degraded": resp.inference_mode != "real",
        "provenance": {
            "model_name": resp.model_name, "model_version": resp.model_version,
            "called": "regulatory:verify", "ran": resp.inference_mode == "real",
            "inference_mode": resp.inference_mode, "confidence": resp.confidence,
            "latency_ms": resp.latency_ms, "artifact_path": resp.artifact_path,
            "degraded_reason": resp.degraded_reason,
            "correlation_id": resp.correlation_id, "scenario_id": resp.scenario_id,
            "timestamp": resp.timestamp,
        },
    }


# --------------------------------------------------------------------------- #
# Node / edge status classification for the graph payload
# --------------------------------------------------------------------------- #
def _zone_status(risk: float, is_cut: bool) -> str:
    if is_cut:
        return "mitigated"
    if risk >= 0.6:
        return "critical"
    if risk >= 0.3:
        return "warning"
    return "normal"


def _build_graph_payload(
    scenario: Scenario,
    graph: SafetyHypergraph,
    zone_risk: dict[str, float],
    activated,
    paths,
    recommendation,
) -> dict[str, Any]:
    snap = graph.snapshot()
    cut_node_ids: set[str] = set()
    cut_edge_ids: set[str] = set()
    intervention_ids: list[str] = []

    # Causal-path membership (nodes/edges that belong to an extracted path).
    causal_nodes: set[str] = set()
    for p in paths:
        causal_nodes.update(p.subgraph.nodes)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Intervention target nodes -> mitigated / cut.
    rec_targets: dict[str, str] = {}
    if recommendation is not None:
        for c in recommendation.interventions:
            intervention_ids.append(c.intervention_id)
            rec_targets[c.target_node] = c.intervention_id
            cut_node_ids.add(c.target_node)

    # --- entity nodes ---
    for n in snap["nodes"]:
        nid = n["id"]
        ntype = n.get("node_type", "unknown")
        is_cut = nid in cut_node_ids
        risk = 0.0
        status = "normal"
        label = n.get("name") or nid

        if ntype == NodeType.ZONE.value:
            risk = round(zone_risk.get(nid, 0.0), 3)
            status = _zone_status(risk, is_cut)
        elif ntype == NodeType.SENSOR.value:
            val = n.get("value")
            zone_thr = 200.0
            # find owning zone threshold
            for z in scenario.zones:
                if any(s.sensor_id == nid and s.zone_id == z.zone_id for s in scenario.sensors):
                    zone_thr = z.baseline_gas_threshold_ppm
            if isinstance(val, (int, float)):
                risk = round(min(1.0, val / _PPM_SATURATION), 3)
                status = "critical" if val >= zone_thr else ("warning" if val >= 0.7 * zone_thr else "normal")
                label = f"{nid} ({val:g}{n.get('unit','')})"
        elif ntype == NodeType.WORKER.value:
            status = "mitigated" if is_cut else ("warning" if not n.get("ppe_compliant", True) else "normal")
            zone = n.get("zone")
            if zone and zone_risk.get(zone, 0.0) >= 0.6 and not is_cut:
                status = "critical"
        elif ntype == NodeType.PERMIT.value:
            if is_cut or n.get("status") in ("suspended", "closed"):
                status = "mitigated"
            elif n.get("permit_type") == "hot_work" and n.get("status") == "active":
                status = "warning"
            label = f"{nid} ({n.get('permit_type','')})"
        elif ntype == NodeType.ASSET.value:
            fp = n.get("failure_probability", 0.0) or 0.0
            risk = round(float(fp), 3)
            status = "critical" if fp >= 0.6 else ("warning" if fp >= 0.3 else "normal")

        nodes.append({
            "id": nid,
            "type": ntype,
            "label": label,
            "status": status,
            "risk": risk,
            "metadata": {
                k: v for k, v in n.items()
                if k not in ("id", "node_type", "created_at") and not isinstance(v, dict)
            } | {"in_causal_path": nid in causal_nodes,
                 "cut": is_cut,
                 "source_event": n.get("info_class")},
        })

    # --- base edges (located_in / monitors / applies_to / adjacent_to) ---
    _REL_LABEL = {
        Relation.IN_ZONE: "located_in",
        Relation.MONITORS: "monitors",
        Relation.APPLIES_TO: "applies_to",
        Relation.PROTECTS: "protects",
        Relation.ADJACENT: "adjacent_to",
        Relation.HELD_BY: "held_by",
    }
    seen_edge = set()
    for e in snap["base_edges"]:
        rel = e.get("relation", "related")
        eid = f"{e['source']}->{e['target']}:{rel}"
        if eid in seen_edge:
            continue
        seen_edge.add(eid)
        edges.append({
            "id": eid,
            "source": e["source"],
            "target": e["target"],
            "relation": _REL_LABEL.get(rel, rel),
            "active": True,
            "causal_path": e["source"] in causal_nodes and e["target"] in causal_nodes,
            "cut": False,
            "metadata": {k: v for k, v in e.items() if k not in ("source", "target")},
        })

    # --- rule / hazard nodes + activates/causes edges ---
    activated_rules: list[dict[str, Any]] = []
    for edge in activated:
        rid = edge.hyperedge_id
        activated_rules.append({
            "id": rid, "pathway": edge.pathway, "severity": round(edge.severity, 3),
            "constituents": list(edge.constituent_nodes),
        })
        nodes.append({
            "id": rid, "type": "rule",
            "label": rid, "status": "critical", "risk": round(edge.severity, 3),
            "metadata": {"pathway": edge.pathway, "kind": "compound_rule"},
        })
        # activates: constituent -> rule
        for cn in edge.constituent_nodes:
            eid = f"{cn}->{rid}:activates"
            edges.append({
                "id": eid, "source": cn, "target": rid, "relation": "activates",
                "active": True, "causal_path": True, "cut": False, "metadata": {},
            })
        # causes: rule -> root zone (predicted harm)
        root_zone = None
        for p in paths:
            if p.hyperedge_id == rid:
                root_zone = p.root_zone
                break
        if root_zone:
            eid = f"{rid}->{root_zone}:causes"
            edges.append({
                "id": eid, "source": rid, "target": root_zone, "relation": "causes",
                "active": True, "causal_path": True, "cut": False,
                "metadata": {"pathway": edge.pathway},
            })

    # --- propagates_to edges from causal-path propagation zones ---
    for p in paths:
        for pz in p.propagation_zones:
            eid = f"{p.root_zone}->{pz}:propagates_to"
            edges.append({
                "id": eid, "source": p.root_zone, "target": pz,
                "relation": "propagates_to", "active": True,
                "causal_path": True, "cut": False, "metadata": {},
            })

    # --- intervention nodes + mitigates edges (the minimum cut) ---
    if recommendation is not None:
        for c in recommendation.interventions:
            iid = c.intervention_id
            nodes.append({
                "id": iid, "type": "intervention", "label": c.action,
                "status": "mitigated", "risk": 0.0,
                "metadata": {"cost": c.cost_category, "disruption": c.disruption,
                             "execution_time_min": c.execution_time_min,
                             "target": c.target_node},
            })
            if c.target_node in {n["id"] for n in nodes}:
                eid = f"{iid}->{c.target_node}:mitigates"
                edges.append({
                    "id": eid, "source": iid, "target": c.target_node,
                    "relation": "mitigates", "active": True,
                    "causal_path": False, "cut": True, "metadata": {},
                })
                cut_edge_ids.add(eid)
            # also cut any activates edge feeding a rule from the target
            for e in edges:
                if e["source"] == c.target_node and e["relation"] == "activates":
                    e["cut"] = True
                    cut_edge_ids.add(e["id"])

    causal_paths = [
        {"hyperedge_id": p.hyperedge_id, "pathway": p.pathway,
         "severity": round(p.severity, 3), "root_zone": p.root_zone,
         "nodes": list(p.subgraph.nodes),
         "contributing_factors": p.contributing_factors,
         "propagation_zones": p.propagation_zones}
        for p in paths
    ]

    return {
        "scenario_id": scenario.scenario_id,
        "nodes": nodes,
        "edges": edges,
        "activated_rules": activated_rules,
        "causal_paths": causal_paths,
        "minimum_cut": {
            "node_ids": sorted(cut_node_ids),
            "edge_ids": sorted(cut_edge_ids),
            "intervention_ids": intervention_ids,
        },
        "graph_revision": graph.revision,
    }


# --------------------------------------------------------------------------- #
# Explanation (template-based; LLM optional per design §9.2)
# --------------------------------------------------------------------------- #
def _explain(scenario, paths, recommendation, tth, citations) -> str:
    if not paths:
        return ("No compound accident pathway is currently active for this "
                "scenario. All monitored conditions are below activation "
                "thresholds.")
    worst = max(paths, key=lambda p: p.severity)
    lines = [
        f"Scenario '{scenario.name}' activated {len(paths)} compound pathway(s). "
        f"The dominant hazard is {worst.pathway.replace('_', ' ')} in "
        f"{worst.root_zone} (severity {worst.severity:.2f})."
    ]
    if tth is not None:
        lines.append(f"Estimated time-to-harm for {worst.root_zone}: ~{tth/60:.1f} minutes [P].")
    if recommendation is not None and recommendation.interventions:
        acts = "; ".join(c.action for c in recommendation.interventions)
        lines.append(
            f"Recommended minimum causal cut ({len(recommendation.interventions)} "
            f"action(s)): {acts}. Projected residual risk "
            f"{recommendation.residual_risk:.2f} vs threshold "
            f"{recommendation.safety_threshold:.2f} "
            f"({'met' if recommendation.threshold_met else 'NOT met'})."
        )
    if citations:
        lines.append("Regulatory basis: " + "; ".join(c["clause"] for c in citations) + " [R].")
    lines.append("This is a recommendation only — no action executes without human approval [H].")
    return " ".join(lines)


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #
def run_scenario(
    scenario: Scenario,
    correlation_id: str | None = None,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Execute the full pipeline for a user scenario. Pure/analytical: no DB I/O.

    Raw model inputs in the scenario (128-dim gas arrays, AI4I machine features,
    hydraulic cycle arrays) are pushed through the SHARED trained-model
    inference services first; their real predictions become canonical events.
    Nothing model-like is fabricated here.

    *progress_callback*, if provided, is called as ``cb(index, stage, label)``
    at each pipeline stage so WebSocket clients can track execution live.
    """
    import time as _time
    import uuid as _uuid
    from app.engine.model_events import generate_model_events

    _STAGES = [
        ("validate", "Input validation"),
        ("events", "Canonical event generation"),
        ("model_inference", "Model inference"),
        ("graph", "Hypergraph construction"),
        ("rules", "Compound-rule detection"),
        ("paths", "Accident-path extraction"),
        ("opt", "Minimum-causal-cut optimisation"),
        ("risk", "Risk propagation"),
        ("sim", "Counterfactual simulation"),
        ("rag", "Regulatory verification"),
        ("explain", "Explanation generation"),
    ]
    _t0 = _time.perf_counter()

    def _progress(idx: int) -> None:
        if progress_callback is not None:
            stage, label = _STAGES[idx]
            try:
                progress_callback({
                    "stage": stage, "label": label,
                    "index": idx, "total": len(_STAGES),
                    "elapsed_ms": round((_time.perf_counter() - _t0) * 1000, 1),
                })
            except Exception:
                pass  # never let progress reporting break the pipeline

    cid = correlation_id or str(_uuid.uuid4())

    _progress(0)  # validate
    _progress(1)  # events

    # --- REAL model inference -> canonical events -------------------------
    _progress(2)  # model_inference
    model_events, model_provenance = generate_model_events(scenario, cid)

    _progress(3)  # graph
    graph = build_graph_from_scenario(scenario, extra_events=model_events)

    return analyse_graph(scenario, graph, model_provenance, cid,
                         model_event_count=len(model_events),
                         progress_callback=progress_callback)


def analyse_graph(
    scenario: Scenario,
    graph: SafetyHypergraph,
    model_provenance: list[dict[str, Any]],
    cid: str,
    model_event_count: int = 0,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Analysis half: rules -> paths -> propagation -> SimPy -> OR-Tools -> RAG.

    Shared by the synchronous runner (offline/unit tests) and the async
    production pipeline, which passes a graph the queue consumer already
    populated from persisted state.
    """
    import time as _time

    _STAGES = [
        ("rule_evaluation", "Compound-rule detection"),
        ("path_extraction", "Accident-path extraction"),
        ("optimization", "Minimum-causal-cut optimisation"),
        ("risk_propagation", "Risk propagation"),
        ("simulation", "Counterfactual simulation"),
        ("regulatory_verification", "Regulatory verification"),
        ("explanation", "Explanation generation"),
    ]
    _t0 = _time.perf_counter()

    def _progress(idx: int) -> None:
        if progress_callback is None:
            return
        stage, label = _STAGES[idx]
        try:
            progress_callback({"stage": stage, "label": label, "index": idx,
                               "total": len(_STAGES),
                               "elapsed_ms": round((_time.perf_counter() - _t0) * 1000, 1)})
        except Exception:
            pass

    _progress(0)  # rule_evaluation
    rules = CompoundRuleEngine(graph)
    extractor = PathExtractor(graph)
    optimiser = MinimumCausalCutOptimiser(scenario.safety_threshold)

    activated = rules.evaluate()
    _progress(1)  # paths
    paths = extractor.extract_all(activated)
    _progress(2)  # opt
    recommendation = optimiser.solve(paths) if paths else None

    # Zone risk / hazard severity from the live graph.
    zone_risk: dict[str, float] = {}
    hazard_severity: dict[str, float] = {}
    for zid in graph.nodes_of_type_zone():
        node = graph.node(zid)
        ppm = node.get("last_gas_ppm") or 0.0
        sev = max(0.0, min(1.0, ppm / _PPM_SATURATION))
        hazard_severity[zid] = sev
        zone_risk[zid] = sev
    # Boost zone risk to the max activated pathway severity in that zone.
    for p in paths:
        zone_risk[p.root_zone] = max(zone_risk.get(p.root_zone, 0.0), p.severity)
        hazard_severity[p.root_zone] = max(hazard_severity.get(p.root_zone, 0.0), p.severity)

    _progress(3)  # risk
    topo = _scenario_topology(scenario)
    prop_inputs = PropagationInputs(risk=dict(zone_risk), hazard_severity=dict(hazard_severity),
                                    barrier_multiplier={})

    watch = paths[0].root_zone if paths else (scenario.zones[0].zone_id)
    tth = estimate_time_to_harm(prop_inputs, zone=watch, threshold=0.75, graph=topo)

    # Baseline vs treated trajectory.
    _progress(4)  # sim
    sim = CounterfactualSimulator(prop_inputs, dt_seconds=10.0, horizon_seconds=300.0, graph=topo)
    baseline = sim.run_baseline()
    zones_sorted = sorted({z for snap in baseline.trajectory for z in snap})
    baseline_series = {z: [snap.get(z, 0.0) for snap in baseline.trajectory] for z in zones_sorted}

    treated_series = None
    treated_label = None
    if paths:
        # Treat by boosting ventilation of the watch zone (maps to a real intervention type).
        treated = sim.run_with_interventions([
            Intervention(time_s=30.0, action="boost_ventilation", target=watch, magnitude=4.0)
        ])
        treated_series = {z: [snap.get(z, 0.0) for snap in treated.trajectory] for z in zones_sorted}
        treated_label = f"Boost ventilation @30s ({watch})"

    # Regulatory verification.
    _progress(5)  # rag
    actions = [c.action for c in recommendation.interventions] if recommendation else []
    zone_ctx = ""
    if paths:
        zone_ctx = f"{paths[0].pathway} in {paths[0].root_zone}"
    reg = (verify_interventions(actions, zone_ctx, correlation_id=cid,
                                scenario_id=scenario.scenario_id)
           if actions else {"citations": [], "degraded": False, "provenance": None})

    _progress(6)  # explain
    graph_payload = _build_graph_payload(scenario, graph, zone_risk, activated, paths, recommendation)

    if reg.get("provenance"):
        model_provenance.append(reg["provenance"])

    warnings: list[str] = []
    if reg.get("degraded") and actions:
        warnings.append("Regulatory retrieval degraded — using static clause fallback. "
                        "Compliance evidence is indicative, not FAISS-verified.")
    for rec in model_provenance:
        if not rec.get("ran"):
            warnings.append(
                f"Model '{rec.get('model_name')}' did not run "
                f"({rec.get('inference_mode')}): {rec.get('degraded_reason')}. "
                "No substitute prediction was generated.")
    if recommendation is not None and not recommendation.threshold_met:
        warnings.append("Recommended cut does NOT bring residual risk below the safety "
                        "threshold — manual review required.")
    if not paths:
        warnings.append("No compound pathway activated — nothing to cut.")

    explanation = _explain(scenario, paths, recommendation, tth, reg["citations"])

    from app.services.model_service import get_registry as _reg
    _status = _reg().status_all()
    ran = [r for r in model_provenance if r.get("ran")]
    execution_mode = "real" if (ran and all(r.get("ran") for r in model_provenance)) else (
        "degraded" if model_provenance else "no_model_inputs")

    return {
        "scenario_id": scenario.scenario_id,
        "scenario_name": scenario.name,
        "correlation_id": cid,
        "execution_mode": execution_mode,
        "models": {
            "invocations": model_provenance,
            "models_called": [r.get("called") for r in model_provenance],
            "models_ran": [r.get("called") for r in ran],
            "models_failed": [r.get("called") for r in model_provenance if not r.get("ran")],
            "mocks_used": False,
            "registry_status": _status,
        },
        "model_events_generated": model_event_count,
        "safety_threshold": scenario.safety_threshold,
        "zone_risk": {z: round(r, 3) for z, r in zone_risk.items()},
        "activated_rules": graph_payload["activated_rules"],
        "causal_paths": [p.to_dict() for p in paths],
        "recommendation": recommendation.to_dict() if recommendation else None,
        "time_to_harm_seconds": tth,
        "risk_timeline": {
            "timestamps_s": baseline.timestamps_s,
            "baseline": baseline_series,
            "treated": treated_series,
            "treated_label": treated_label,
            "watch_zone": watch,
        },
        "regulatory_citations": reg["citations"],
        "explanation": explanation,
        "warnings": warnings,
        "graph": graph_payload,
    }

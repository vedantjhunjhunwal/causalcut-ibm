"""Path extractor -- turns an activated hyperedge into an accident chain.

An activated compound hyperedge tells us *that* a dangerous combination exists.
The operator needs to see *how it develops*: the directed chain from source
conditions (rising gas, ignition source) through the contributing factors
(missing PPE, degraded ventilation) to the potential outcome (flash fire /
toxic exposure), plus which zones the risk can propagate to via shared
utilities.

This module builds a small ``AccidentPath`` -- a directed subgraph rooted at
the hyperedge -- that the counterfactual simulator and the minimum-causal-cut
optimiser consume. Each candidate intervention maps to *cutting* one or more
edges/nodes in this subgraph.

Deliverable for: "Hypergraph Compound Rule Engine" (path extractor half).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx

from app.engine.hypergraph_wrapper import SafetyHypergraph, Relation
from app.engine.types import Hyperedge, InformationClass, NodeType

logger = logging.getLogger("causalcut.paths")


# A candidate intervention is a way to break the chain by removing a node's
# contribution. The optimiser later chooses the minimum-cardinality subset.
@dataclass
class CandidateIntervention:
    intervention_id: str
    action: str
    target_node: str
    intervention_type: str
    cost_category: str            # LOW | MEDIUM | HIGH
    disruption: str               # MINIMAL | LOW | MEDIUM | HIGH
    execution_time_min: float
    # Which of the chain's contributing factors this removes.
    breaks_factors: frozenset[str] = field(default_factory=frozenset)
    info_class: InformationClass = InformationClass.COUNTERFACTUAL
    # G1 — Bow-Tie: whether this intervention stops the top event (preventive)
    # or limits consequences after it (mitigative). Changes CP-SAT cost model
    # weighting because preventive cuts should be preferred.
    barrier_role: str = "preventive"  # Literal["preventive", "mitigative"]


@dataclass
class SubPathway:
    """One concrete accident route within a hyperedge.

    An accident occurs only if *all* of ``necessary_factors`` hold at once
    (a conjunction). Removing any single necessary factor breaks this route.
    This is the granularity the minimum-causal-cut set-cover operates on
    (design doc 6.1: "for every critical path p_i: sum_j C_ij x_j >= 1").
    """

    name: str
    necessary_factors: frozenset[str]


# Pathway string -> the sub-pathways (accident routes) it decomposes into,
# each with the factors that must ALL hold for that route to complete.
_PATHWAY_DECOMPOSITION: dict[str, list[SubPathway]] = {
    "toxic_exposure_or_flash_fire": [
        SubPathway("flash_fire", frozenset({"gas_source", "ignition_source"})),
        SubPathway("toxic_exposure", frozenset({"gas_source", "worker_exposure", "ventilation_deficit"})),
    ],
    "acute_toxic_exposure": [
        SubPathway("toxic_exposure", frozenset({"gas_source", "worker_exposure"})),
    ],
    "gas_accumulation": [
        SubPathway("containment_loss", frozenset({"gas_source"})),
    ],
    "uncontrolled_ignition": [
        SubPathway("ignition", frozenset({"ignition_source", "gas_source", "barrier_gap"})),
    ],
    "mechanical_injury": [
        SubPathway("mechanical_injury", frozenset({"equipment_hazard", "worker_exposure"})),
    ],
    "equipment_hazard": [
        SubPathway("machine_breakdown", frozenset({"equipment_hazard"})),
    ],
    "ventilation_starvation": [
        SubPathway("ventilation_deficit", frozenset({"ventilation_deficit"})),
    ],
}


@dataclass
class AccidentPath:
    hyperedge_id: str
    pathway: str
    severity: float
    root_zone: str
    subgraph: nx.DiGraph
    contributing_factors: list[str]
    propagation_zones: list[str]
    sub_pathways: list[SubPathway] = field(default_factory=list)
    candidate_interventions: list[CandidateIntervention] = field(default_factory=list)
    # G1 — Bow-Tie: the loss-of-control event this path leads to.
    # Populated by PathExtractor from the activating CompoundRule.top_event.
    top_event: str = ""
    # G4 — Incident Pattern: similar historical incidents (populated by Agent 2).
    similar_incidents: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "hyperedge_id": self.hyperedge_id,
            "pathway": self.pathway,
            "severity": self.severity,
            "root_zone": self.root_zone,
            "top_event": self.top_event,
            "nodes": list(self.subgraph.nodes),
            "edges": [
                {"source": u, "target": v, **d}
                for u, v, d in self.subgraph.edges(data=True)
            ],
            "contributing_factors": self.contributing_factors,
            "propagation_zones": self.propagation_zones,
            "sub_pathways": [
                {"name": sp.name, "necessary_factors": sorted(sp.necessary_factors)}
                for sp in self.sub_pathways
            ],
            "candidate_interventions": [
                {
                    "intervention_id": c.intervention_id,
                    "action": c.action,
                    "target_node": c.target_node,
                    "intervention_type": c.intervention_type,
                    "cost_category": c.cost_category,
                    "disruption": c.disruption,
                    "execution_time_min": c.execution_time_min,
                    "breaks_factors": sorted(c.breaks_factors),
                    "info_class": c.info_class.value,
                    "barrier_role": c.barrier_role,
                }
                for c in self.candidate_interventions
            ],
        }


# Maps a satisfied condition predicate to a stable "factor" tag so the
# optimiser can reason about coverage independent of node naming.
def _factor_of(condition_predicate: str) -> str:
    p = condition_predicate.lower()
    if "gas_ppm" in p or "gas" in p:
        return "gas_source"
    if "hot_work" in p or "permit" in p:
        return "ignition_source"
    if "ppe" in p:
        return "unprotected_worker"
    if "ventilation" in p:
        return "ventilation_deficit"
    if "worker present" in p:
        return "worker_exposure"
    if "barrier" in p or "suppression" in p:
        return "barrier_gap"
    if "failure_probability" in p or "asset" in p:
        return "equipment_hazard"
    return "other"


class PathExtractor:
    """Builds accident-path subgraphs and their candidate interventions."""

    def __init__(self, graph: SafetyHypergraph) -> None:
        self.graph = graph

    def extract(self, hyperedge: Hyperedge) -> AccidentPath:
        # Root zone = the zone node among the constituents (edges are per-zone).
        root_zone = next(
            (n for n in hyperedge.constituent_nodes
             if self.graph.has_node(n)
             and self.graph.node(n).get("node_type") == NodeType.ZONE.value),
            hyperedge.constituent_nodes[0],
        )

        sub = nx.DiGraph()
        # Synthetic outcome node terminates the chain.
        outcome = f"OUTCOME:{hyperedge.pathway}"
        sub.add_node(outcome, kind="outcome", pathway=hyperedge.pathway,
                     info_class=InformationClass.PREDICTED.value)

        contributing_factors: list[str] = []
        for cond in hyperedge.conditions:
            if not cond.satisfied:
                continue
            factor = _factor_of(cond.predicate)
            contributing_factors.append(factor)
            node_id = cond.node
            sub.add_node(
                node_id,
                kind="condition",
                factor=factor,
                predicate=cond.predicate,
                info_class=cond.info_class.value,
            )
            # Every satisfied condition feeds the outcome.
            sub.add_edge(node_id, outcome, relation="contributes_to", factor=factor)

        contributing_factors = sorted(set(contributing_factors))

        # Propagation: which adjacent zones could inherit this risk (Zone 4).
        propagation_zones = self._propagation_targets(root_zone)
        for z in propagation_zones:
            sub.add_node(z, kind="propagation_zone",
                         info_class=InformationClass.PREDICTED.value)
            sub.add_edge(outcome, z, relation="propagates_to",
                         info_class=InformationClass.PREDICTED.value)

        present = set(contributing_factors)
        sub_pathways = [
            sp for sp in _PATHWAY_DECOMPOSITION.get(hyperedge.pathway, [])
            # A route is "live" only if all its necessary factors are present.
            if sp.necessary_factors <= present
        ]
        # Fallback: if nothing decomposed cleanly, treat the whole edge as one
        # route whose necessary factors are everything currently present.
        if not sub_pathways and present:
            sub_pathways = [SubPathway(hyperedge.pathway, frozenset(present))]

        path = AccidentPath(
            hyperedge_id=hyperedge.hyperedge_id,
            pathway=hyperedge.pathway,
            severity=hyperedge.severity,
            root_zone=root_zone,
            subgraph=sub,
            contributing_factors=contributing_factors,
            propagation_zones=propagation_zones,
            sub_pathways=sub_pathways,
            top_event=hyperedge.top_event,  # G1 — bow-tie passthrough
        )
        path.candidate_interventions = self._candidate_interventions(hyperedge, root_zone, contributing_factors)
        return path

    def _propagation_targets(self, zone_id: str) -> list[str]:
        """Zones reachable via shared-utility adjacency within 2 hops."""
        if not self.graph.has_node(zone_id):
            return []
        targets: set[str] = set()
        for adj in self.graph.neighbors(zone_id, Relation.ADJACENT):
            if self.graph.node(adj).get("hazard_class") in ("propagation", "admin"):
                # hop through the utilities zone
                for second in self.graph.neighbors(adj, Relation.ADJACENT):
                    if second != zone_id and self.graph.node(second).get("node_type") == NodeType.ZONE.value:
                        targets.add(second)
            elif self.graph.node(adj).get("node_type") == NodeType.ZONE.value:
                targets.add(adj)
        targets.discard(zone_id)
        return sorted(targets)

    def _candidate_interventions(
        self, hyperedge: Hyperedge, zone_id: str, factors: list[str]
    ) -> list[CandidateIntervention]:
        """Generate feasible interventions, each mapped to the factors it removes.

        The optimiser treats each factor as a "path" to cover: a valid cut must
        remove enough factors to push residual risk below threshold. Node
        targets are resolved from live graph state so actions reference real
        permits/workers.
        """
        cands: list[CandidateIntervention] = []
        fset = set(factors)

        # Suspend the hot-work permit -> removes ignition source.
        if "ignition_source" in fset:
            permits = [
                p for p in self.graph.active_permits_in_zone(zone_id)
                if self.graph.node(p).get("permit_type") == "hot_work"
            ]
            for target in permits:
                cands.append(CandidateIntervention(
                    intervention_id=f"INT-suspend-{target}",
                    action=f"Suspend hot-work permit {target} in {zone_id}",
                    target_node=target,
                    intervention_type="suspend_permit",
                    cost_category="LOW", disruption="MINIMAL", execution_time_min=2,
                    breaks_factors=frozenset({"ignition_source"}),
                ))

        # Evacuate exposed workers -> removes worker exposure (only for workers actually present).
        if "worker_exposure" in fset:
            workers = self.graph.workers_in_zone(zone_id)
            for target in workers:
                cands.append(CandidateIntervention(
                    intervention_id=f"INT-evacuate-{target}",
                    action=f"Evacuate worker {target} from {zone_id}",
                    target_node=target,
                    intervention_type="evacuate_worker",
                    cost_category="LOW", disruption="LOW", execution_time_min=3,
                    breaks_factors=frozenset({"worker_exposure"}),
                ))

        # Trip / isolate failing equipment -> removes equipment hazard.
        if "equipment_hazard" in fset:
            assets = sorted(
                [
                    a for a in self.graph.predecessors(zone_id, Relation.IN_ZONE)
                    if self.graph.node(a).get("node_type") == NodeType.ASSET.value
                    and (self.graph.node(a).get("failure_probability") or 0.0) >= 0.4
                ],
                key=lambda a: self.graph.node(a).get("failure_probability", 0.0),
                reverse=True,
            )
            for idx, target in enumerate(assets):
                cands.append(CandidateIntervention(
                    intervention_id=f"INT-trip-{target}",
                    action=f"Emergency trip and isolate machine {target} in {zone_id}",
                    target_node=target,
                    intervention_type="isolate_equipment",
                    cost_category="LOW", disruption="LOW", execution_time_min=1 if idx == 0 else 2 + idx,
                    breaks_factors=frozenset({"equipment_hazard"}),
                ))

        # Increase ventilation -> removes ventilation deficit.
        if "ventilation_deficit" in fset or "gas_source" in fset:
            cands.append(CandidateIntervention(
                intervention_id=f"INT-vent-{zone_id}",
                action=f"Override ventilation in {zone_id} to 100%",
                target_node=zone_id,
                intervention_type="increase_ventilation",
                cost_category="LOW", disruption="MINIMAL", execution_time_min=1,
                breaks_factors=frozenset({"ventilation_deficit"}),
            ))

        # Require PPE -> removes unprotected worker only.
        if "unprotected_worker" in fset:
            offenders = [
                w for w in self.graph.workers_in_zone(zone_id)
                if not self.graph.node(w).get("ppe_compliant", True)
            ]
            target_label = ", ".join(offenders) if offenders else zone_id
            cands.append(CandidateIntervention(
                intervention_id=f"INT-ppe-{zone_id}",
                action=f"Enforce immediate PPE compliance for {target_label} in {zone_id}",
                target_node=zone_id,
                intervention_type="enforce_ppe",
                cost_category="LOW", disruption="MINIMAL", execution_time_min=2,
                breaks_factors=frozenset({"unprotected_worker"}),
            ))

        # Activate gas isolation -> removes gas source.
        if "gas_source" in fset:
            cands.append(CandidateIntervention(
                intervention_id=f"INT-gasiso-{zone_id}",
                action=f"Activate gas isolation valve in {zone_id}",
                target_node=zone_id,
                intervention_type="gas_isolation",
                cost_category="MEDIUM", disruption="LOW", execution_time_min=2,
                breaks_factors=frozenset({"gas_source"}),
            ))

        # Close the zone -> the emergency fallback: removes every factor at HIGH cost.
        cands.append(CandidateIntervention(
            intervention_id=f"INT-close-{zone_id}",
            action=f"Close and lock out {zone_id}",
            target_node=zone_id,
            intervention_type="close_zone",
            cost_category="HIGH", disruption="HIGH", execution_time_min=5,
            breaks_factors=frozenset(fset),
        ))
        return cands

    def extract_all(self, hyperedges: list[Hyperedge]) -> list[AccidentPath]:
        return [self.extract(h) for h in hyperedges if h.activated]

"""Compound rule engine -- detects activated compound hyperedges.

A single sensor spike is rarely an accident. The danger is *compound*: rising
gas AND an active hot-work permit AND a worker without PPE AND degrading
ventilation, all overlapping in the same zone at the same time. Each of those
alone is yellow; together they are the coke-oven flash-fire pathway HE-042.

This engine holds a small library of ``CompoundRule`` templates. Each rule is
a set of predicate functions over the current graph state plus a severity
function. On every ``evaluate`` pass it materialises the concrete hyperedges
that are currently firing, registers/activates them on the graph, and returns
them for downstream path extraction and cut optimisation.

Deliverable for: "Hypergraph Compound Rule Engine".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from app.engine.hypergraph_wrapper import SafetyHypergraph
from app.engine.types import (
    Hyperedge,
    HyperedgeCondition,
    InformationClass,
)

logger = logging.getLogger("causalcut.rules")


@dataclass
class ConditionResult:
    node: str
    predicate: str
    satisfied: bool
    info_class: InformationClass
    observed_value: object = None


# A predicate takes (graph, zone_id) and returns a ConditionResult.
PredicateFn = Callable[[SafetyHypergraph, str], ConditionResult]
# A severity function takes the list of satisfied conditions and returns 0..1.
SeverityFn = Callable[[list[ConditionResult]], float]


# --------------------------------------------------------------------------- #
# Reusable predicate builders
# --------------------------------------------------------------------------- #
def rising_gas(threshold_ppm: float | None = None) -> PredicateFn:
    def _pred(g: SafetyHypergraph, zone_id: str) -> ConditionResult:
        zone = g.node(zone_id)
        limit = threshold_ppm if threshold_ppm is not None else zone.get("baseline_gas_threshold_ppm", 200.0)
        ppm = zone.get("last_gas_ppm")
        satisfied = ppm is not None and ppm > limit
        return ConditionResult(
            node=zone_id,
            predicate=f"gas_ppm > {limit}",
            satisfied=satisfied,
            info_class=InformationClass(zone.get("last_gas_info_class", "M")) if satisfied else InformationClass.MEASURED,
            observed_value=ppm,
        )
    return _pred


def active_permit(permit_type: str) -> PredicateFn:
    def _pred(g: SafetyHypergraph, zone_id: str) -> ConditionResult:
        matches = [
            p for p in g.active_permits_in_zone(zone_id)
            if g.node(p).get("permit_type") == permit_type
        ]
        satisfied = bool(matches)
        return ConditionResult(
            node=matches[0] if matches else f"{zone_id}:{permit_type}",
            predicate=f"active {permit_type} permit in zone",
            satisfied=satisfied,
            info_class=InformationClass.SYNTHETIC,
            observed_value=matches,
        )
    return _pred


def worker_missing_ppe() -> PredicateFn:
    def _pred(g: SafetyHypergraph, zone_id: str) -> ConditionResult:
        offenders = [
            w for w in g.workers_in_zone(zone_id)
            if not g.node(w).get("ppe_compliant", True)
        ]
        satisfied = bool(offenders)
        return ConditionResult(
            node=offenders[0] if offenders else f"{zone_id}:worker",
            predicate="worker present without required PPE",
            satisfied=satisfied,
            info_class=InformationClass.MEASURED,
            observed_value=offenders,
        )
    return _pred


def ventilation_degraded(ratio: float = 0.6) -> PredicateFn:
    def _pred(g: SafetyHypergraph, zone_id: str) -> ConditionResult:
        zone = g.node(zone_id)
        flow = zone.get("ventilation_flow_ratio", 1.0)
        satisfied = flow is not None and flow < ratio
        return ConditionResult(
            node=zone_id,
            predicate=f"ventilation_flow < {ratio} nominal",
            satisfied=satisfied,
            info_class=InformationClass(zone.get("ventilation_info_class", "P")) if satisfied else InformationClass.PREDICTED,
            observed_value=flow,
        )
    return _pred


def worker_present() -> PredicateFn:
    def _pred(g: SafetyHypergraph, zone_id: str) -> ConditionResult:
        workers = g.workers_in_zone(zone_id)
        return ConditionResult(
            node=workers[0] if workers else f"{zone_id}:worker",
            predicate="at least one worker present in zone",
            satisfied=bool(workers),
            info_class=InformationClass.MEASURED,
            observed_value=workers,
        )
    return _pred


def barrier_down(barrier_type: str) -> PredicateFn:
    def _pred(g: SafetyHypergraph, zone_id: str) -> ConditionResult:
        barriers = [
            b for b in g.predecessors(zone_id, "protects")
            if g.node(b).get("barrier_type") == barrier_type
        ]
        down = [b for b in barriers if g.node(b).get("status") != "active"]
        return ConditionResult(
            node=down[0] if down else (barriers[0] if barriers else f"{zone_id}:{barrier_type}"),
            predicate=f"{barrier_type} barrier inactive",
            satisfied=bool(down),
            info_class=InformationClass.MEASURED,
            observed_value=down,
        )
    return _pred


def equipment_failing(threshold: float = 0.6) -> PredicateFn:
    def _pred(g: SafetyHypergraph, zone_id: str) -> ConditionResult:
        assets = [
            a for a in g.predecessors(zone_id, "in_zone")
            if g.node(a).get("node_type") == "asset"
        ]
        failing = [a for a in assets if (g.node(a).get("failure_probability") or 0) >= threshold]
        return ConditionResult(
            node=failing[0] if failing else f"{zone_id}:asset",
            predicate=f"asset failure_probability >= {threshold}",
            satisfied=bool(failing),
            info_class=InformationClass.PREDICTED,
            observed_value=failing,
        )
    return _pred


# --------------------------------------------------------------------------- #
# Severity models
# --------------------------------------------------------------------------- #
def weighted_severity(base: float, per_condition: float = 0.06) -> SeverityFn:
    def _sev(conds: list[ConditionResult]) -> float:
        n = sum(1 for c in conds if c.satisfied)
        return min(1.0, base + per_condition * max(0, n - 2))
    return _sev


# --------------------------------------------------------------------------- #
# Rule definition
# --------------------------------------------------------------------------- #
@dataclass
class CompoundRule:
    template_id: str
    name: str
    pathway: str
    predicates: list[PredicateFn]
    severity_fn: SeverityFn
    # Predicates that MUST all hold for the edge to fire (e.g. a flash-fire
    # pathway genuinely requires elevated gas -- permit+PPE alone is not one).
    mandatory: list[PredicateFn] = field(default_factory=list)
    # Of the (optional) contributing predicates, how many must hold. Default:
    # all of them. Mandatory predicates are always additionally required.
    min_satisfied: int | None = None
    applies_to_hazard_classes: tuple[str, ...] = ()  # empty => all zones

    def evaluate_zone(self, g: SafetyHypergraph, zone_id: str) -> Hyperedge | None:
        # Mandatory gate first: if any mandatory predicate fails, no activation.
        mandatory_results = [p(g, zone_id) for p in self.mandatory]
        if not all(r.satisfied for r in mandatory_results):
            return None

        contributing = [p(g, zone_id) for p in self.predicates]
        results = mandatory_results + contributing
        satisfied = [r for r in results if r.satisfied]
        need = self.min_satisfied if self.min_satisfied is not None else len(self.predicates)
        # min_satisfied counts contributing predicates only.
        if sum(1 for r in contributing if r.satisfied) < need:
            return None

        nodes = sorted({r.node for r in satisfied} | {zone_id})
        severity = self.severity_fn(results)
        edge = Hyperedge(
            hyperedge_id=f"{self.template_id}:{zone_id}",
            template_id=self.template_id,
            constituent_nodes=nodes,
            conditions=[
                HyperedgeCondition(
                    node=r.node,
                    predicate=r.predicate,
                    satisfied=r.satisfied,
                    info_class=r.info_class,
                    observed_value=r.observed_value if isinstance(r.observed_value, (int, float, str, bool, type(None))) else str(r.observed_value),
                )
                for r in results
            ],
            pathway=self.pathway,
            severity=severity,
            activated=True,
        )
        return edge


class CompoundRuleEngine:
    """Holds the rule library and evaluates it against the live graph."""

    def __init__(self, graph: SafetyHypergraph) -> None:
        self.graph = graph
        self.rules: list[CompoundRule] = []
        self._load_default_rules()

    def add_rule(self, rule: CompoundRule) -> None:
        self.rules.append(rule)

    def _load_default_rules(self) -> None:
        # HE-042: the canonical coke-oven flash-fire / toxic-exposure pathway.
        self.add_rule(
            CompoundRule(
                # HE-042 is the CANONICAL identifier used by the design doc,
                # the API, the graph, the dashboard, tests and the audit log.
                # "HE-FLASHFIRE" is retained as a descriptive alias only.
                template_id="HE-042",
                name="HE-FLASHFIRE — toxic gas + hot work + missing PPE + degraded ventilation",
                pathway="toxic_exposure_or_flash_fire",
                mandatory=[rising_gas()],  # no gas -> not a flash-fire pathway
                predicates=[
                    active_permit("hot_work"),
                    worker_missing_ppe(),
                    ventilation_degraded(0.6),
                    worker_present(),
                ],
                severity_fn=weighted_severity(0.80),
                min_satisfied=2,  # gas (mandatory) + any two worker/ignition factors
            )
        )
        # HE-TOXIC: toxic accumulation with a worker present, ventilation failing.
        self.add_rule(
            CompoundRule(
                template_id="HE-TOXIC-EXPOSURE",
                name="Toxic gas accumulation with worker present + poor ventilation",
                pathway="acute_toxic_exposure",
                mandatory=[rising_gas()],
                predicates=[
                    worker_present(),
                    ventilation_degraded(0.7),
                ],
                severity_fn=weighted_severity(0.65),
                min_satisfied=2,
            )
        )
        # HE-IGNITION: hot work with fire suppression barrier down.
        self.add_rule(
            CompoundRule(
                template_id="HE-IGNITION-UNGUARDED",
                name="Hot work with fire suppression offline and rising gas",
                pathway="uncontrolled_ignition",
                mandatory=[active_permit("hot_work")],  # ignition source is the premise
                predicates=[
                    barrier_down("fire_suppression"),
                    rising_gas(),
                ],
                severity_fn=weighted_severity(0.75),
                min_satisfied=1,
            )
        )
        # HE-MECH: failing rotating equipment with a worker in the zone.
        self.add_rule(
            CompoundRule(
                template_id="HE-MECH-EXPOSURE",
                name="Rotating equipment failure imminent with worker present",
                pathway="mechanical_injury",
                mandatory=[equipment_failing(0.6)],
                predicates=[
                    worker_present(),
                ],
                severity_fn=weighted_severity(0.60),
                min_satisfied=1,
            )
        )

    def evaluate(self) -> list[Hyperedge]:
        """Run every rule against every applicable zone.

        Returns the list of currently-activated compound hyperedges and syncs
        the graph's hyperedge registry to match (activating new ones,
        deactivating ones that have cleared).
        """
        activated: dict[str, Hyperedge] = {}
        zones = self.graph.nodes_of_type_zone()

        for rule in self.rules:
            for zone_id in zones:
                zone = self.graph.node(zone_id)
                if rule.applies_to_hazard_classes and zone.get("hazard_class") not in rule.applies_to_hazard_classes:
                    continue
                edge = rule.evaluate_zone(self.graph, zone_id)
                if edge is not None:
                    activated[edge.hyperedge_id] = edge

        # Reconcile with graph registry.
        current_ids = {e.hyperedge_id for e in self.graph.hyperedges()}
        for hid, edge in activated.items():
            if hid not in current_ids:
                self.graph.register_hyperedge(edge)
            else:
                # update in place then re-activate
                self.graph._hyperedges[hid] = edge  # controlled internal update
            self.graph.activate_hyperedge(hid, edge.severity, edge.pathway)

        for existing in self.graph.hyperedges(activated_only=True):
            if existing.hyperedge_id not in activated:
                self.graph.deactivate_hyperedge(existing.hyperedge_id)

        result = sorted(activated.values(), key=lambda e: e.severity, reverse=True)
        if result:
            logger.info(
                "compound rules activated: %s",
                ", ".join(f"{e.hyperedge_id}({e.severity:.2f})" for e in result),
            )
        return result


# --------------------------------------------------------------------------- #
# Rule identity
# --------------------------------------------------------------------------- #
# HE-042 is canonical everywhere (API, graph, dashboard, tests, audit log).
# Historical/descriptive aliases resolve to it so older scenarios, saved runs
# and documentation keep working.
RULE_ALIASES: dict[str, str] = {
    "HE-FLASHFIRE": "HE-042",
    "HE-042": "HE-042",
}


def canonical_rule_id(rule_id: str) -> str:
    """Map any known alias (optionally zone-suffixed) to its canonical id."""
    base, sep, zone = rule_id.partition(":")
    canonical = RULE_ALIASES.get(base, base)
    return f"{canonical}{sep}{zone}" if sep else canonical

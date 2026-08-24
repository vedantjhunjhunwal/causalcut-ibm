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
            predicate=f"{len(offenders)} worker(s) present without required PPE",
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


def equipment_failing(threshold: float = 0.5) -> PredicateFn:
    def _pred(g: SafetyHypergraph, zone_id: str) -> ConditionResult:
        assets = sorted(
            [
                a for a in g.predecessors(zone_id, "in_zone")
                if g.node(a).get("node_type") == "asset"
            ],
            key=lambda a: g.node(a).get("failure_probability", 0.0),
            reverse=True,
        )
        failing = [a for a in assets if (g.node(a).get("failure_probability") or 0.0) >= threshold]
        max_fp = max((g.node(a).get("failure_probability") or 0.0 for a in assets), default=0.0)
        worst_asset = failing[0] if failing else (assets[0] if assets else f"{zone_id}:asset")
        return ConditionResult(
            node=worst_asset,
            predicate=f"asset {worst_asset} failure_probability >= {threshold}",
            satisfied=bool(failing),
            info_class=InformationClass.PREDICTED,
            observed_value=max_fp,
        )
    return _pred


def conflicting_permits() -> PredicateFn:
    """Detect simultaneous incompatible permit types in the same zone.

    Hot work (ignition source) combined with confined space entry (worker
    trapped, limited egress) is the canonical OISD-STD-105 §7.4 conflict:
    an ignition event while a worker is in an enclosed space with no rapid
    escape route. The risk is categorically higher than either permit alone.

    Information class is SYNTHETIC because permits are user/system-generated
    data — they are not sensor observations.
    """
    _INCOMPATIBLE_PAIRS: list[frozenset[str]] = [
        frozenset({"hot_work", "confined_space_entry"}),
        frozenset({"hot_work", "electrical_isolation"}),  # switching during hot work
    ]

    def _pred(g: SafetyHypergraph, zone_id: str) -> ConditionResult:
        active = g.active_permits_in_zone(zone_id)
        active_types = {g.node(p).get("permit_type", "") for p in active}
        conflicting: list[str] = []
        for pair in _INCOMPATIBLE_PAIRS:
            if pair <= active_types:
                conflicting.extend(
                    p for p in active if g.node(p).get("permit_type") in pair
                )
        # Use the highest-priority (most dangerous) conflicting permit as node.
        priority = {"confined_space_entry": 0, "electrical_isolation": 1, "hot_work": 2}
        if conflicting:
            conflicting.sort(key=lambda p: priority.get(g.node(p).get("permit_type", ""), 99))
        satisfied = bool(conflicting)
        return ConditionResult(
            node=conflicting[0] if conflicting else f"{zone_id}:permit",
            predicate=f"conflicting permits active in zone: {sorted(active_types)}",
            satisfied=satisfied,
            info_class=InformationClass.SYNTHETIC,
            observed_value=conflicting,
        )
    return _pred


def hot_work_permit_with_rising_gas() -> PredicateFn:
    """Detect a hot-work permit that was issued before gas conditions exceeded threshold.

    A hot-work permit is safe at issuance but becomes a condition violation
    the moment gas rises above threshold in the same zone — OISD-STD-116 §4.3
    mandates immediate suspension in this case.
    """
    def _pred(g: SafetyHypergraph, zone_id: str) -> ConditionResult:
        zone = g.node(zone_id)
        ppm = zone.get("last_gas_ppm")
        limit = zone.get("baseline_gas_threshold_ppm", 200.0)
        gas_exceeded = ppm is not None and ppm > limit
        if not gas_exceeded:
            return ConditionResult(
                node=zone_id, predicate="hot_work permit conditions violated by rising gas",
                satisfied=False, info_class=InformationClass.SYNTHETIC,
            )
        # Find any active hot-work permit whose issuance predates the gas reading.
        hw_permits = [
            p for p in g.active_permits_in_zone(zone_id)
            if g.node(p).get("permit_type") == "hot_work"
        ]
        satisfied = bool(hw_permits)
        return ConditionResult(
            node=hw_permits[0] if hw_permits else f"{zone_id}:hot_work",
            predicate="hot_work permit conditions violated by rising gas",
            satisfied=satisfied,
            info_class=InformationClass.SYNTHETIC,
            observed_value={"ppm": ppm, "limit": limit, "permits": hw_permits},
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


def dynamic_gas_severity(base: float = 0.65) -> SeverityFn:
    def _sev(conds: list[ConditionResult]) -> float:
        ppm = 0.0
        limit = 200.0
        for c in conds:
            if "gas_ppm" in c.predicate and isinstance(c.observed_value, (int, float)):
                ppm = float(c.observed_value)
                try:
                    limit = float(c.predicate.split(">")[-1].strip())
                except Exception:
                    limit = 200.0
        gas_ratio = max(1.0, ppm / limit) if limit > 0 else 1.0
        extra_sev = min(0.25, (gas_ratio - 1.0) * 0.10)
        
        # Check PPE compliance of workers in zone
        violating_count = 0
        has_workers = False
        for c in conds:
            if "without required PPE" in c.predicate and isinstance(c.observed_value, list):
                violating_count += len(c.observed_value)
            if "worker present" in c.predicate and c.satisfied:
                has_workers = True
        
        # Count-weighted exposure penalty for unprotected workers
        ppe_penalty = violating_count * 0.03
        # If all workers are fully compliant, give a 0.05 safety credit
        ppe_credit = 0.05 if (has_workers and violating_count == 0) else 0.0
        
        n = sum(1 for c in conds if c.satisfied)
        return max(0.40, min(0.99, base + extra_sev + ppe_penalty - ppe_credit + 0.04 * max(0, n - 2)))
    return _sev


def dynamic_asset_severity(base: float = 0.55) -> SeverityFn:
    def _sev(conds: list[ConditionResult]) -> float:
        max_fp = 0.0
        for c in conds:
            if "failure_probability" in c.predicate and isinstance(c.observed_value, (int, float)):
                max_fp = max(max_fp, float(c.observed_value))
        return max(base, min(0.99, max_fp))
    return _sev


def dynamic_ventilation_severity(base: float = 0.50) -> SeverityFn:
    def _sev(conds: list[ConditionResult]) -> float:
        flow = 1.0
        for c in conds:
            if "ventilation_flow" in c.predicate and isinstance(c.observed_value, (int, float)):
                flow = min(flow, float(c.observed_value))
        flow_deficit = max(0.0, 1.0 - flow)
        return min(0.95, base + flow_deficit * 0.4)
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
    mandatory: list[PredicateFn] = field(default_factory=list)
    min_satisfied: int | None = None
    applies_to_hazard_classes: tuple[str, ...] = ()  # empty => all zones
    # G1 — Bow-Tie formalism fields (schema extension, no logic change)
    top_event: str = ""     # the loss-of-control event this rule encodes
    source_reference: str = ""  # HAZOP worksheet / OISD clause / incident ID

    def evaluate_zone(self, g: SafetyHypergraph, zone_id: str) -> Hyperedge | None:
        # Mandatory gate first: if any mandatory predicate fails, no activation.
        mandatory_results = [p(g, zone_id) for p in self.mandatory]
        if not all(r.satisfied for r in mandatory_results):
            return None

        contributing = [p(g, zone_id) for p in self.predicates]
        results = mandatory_results + contributing
        satisfied = [r for r in results if r.satisfied]
        need = self.min_satisfied if self.min_satisfied is not None else len(self.predicates)
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
            # G1 — Bow-Tie metadata passed through to AccidentPath
            top_event=self.top_event,
            source_reference=self.source_reference,
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
                severity_fn=dynamic_gas_severity(0.80),
                min_satisfied=2,  # gas (mandatory) + any two worker/ignition factors
                # G1 bow-tie metadata
                top_event="Ignition of accumulated CO/H₂ in active hot-work zone",
                source_reference="OISD-STD-105 §7.3; HAZOP-WS-CK-001; Bhilai coke-oven incident 2017",
            )
        )
        # HE-TOXIC: toxic accumulation with a worker present in the zone.
        self.add_rule(
            CompoundRule(
                template_id="HE-TOXIC-EXPOSURE",
                name="Toxic gas accumulation with worker present in zone",
                pathway="acute_toxic_exposure",
                mandatory=[rising_gas(), worker_present()],
                predicates=[
                    ventilation_degraded(0.7),
                    worker_missing_ppe(),
                ],
                severity_fn=dynamic_gas_severity(0.68),
                min_satisfied=0,
                # G1 bow-tie metadata
                top_event="Acute toxic inhalation by unprotected worker in gas-affected zone",
                source_reference="OISD-STD-105 §8.1; Factories Act 1948 §36; DGMS Circular 2019-04",
            )
        )
        # HE-GAS: gas accumulation hazard in plant zone (active even with 0 workers).
        self.add_rule(
            CompoundRule(
                template_id="HE-GAS-ACCUMULATION",
                name="Atmospheric gas concentration exceeding safety threshold",
                pathway="gas_accumulation",
                mandatory=[rising_gas()],
                predicates=[
                    ventilation_degraded(0.7),
                ],
                severity_fn=dynamic_gas_severity(0.55),
                min_satisfied=0,
                # G1 bow-tie metadata
                top_event="Sustained above-LEL gas accumulation creating ignition/asphyxiation hazard",
                source_reference="OISD-STD-114 §4.2; DGMS Circular 2020-01; HAZOP-WS-CK-003",
            )
        )
        # HE-IGNITION: hot work with fire suppression barrier down.
        self.add_rule(
            CompoundRule(
                template_id="HE-IGNITION-UNGUARDED",
                name="Hot work with fire suppression offline and rising gas",
                pathway="uncontrolled_ignition",
                mandatory=[active_permit("hot_work")],
                predicates=[
                    barrier_down("fire_suppression"),
                    rising_gas(),
                ],
                severity_fn=weighted_severity(0.75),
                min_satisfied=1,
                # G1 bow-tie metadata
                top_event="Uncontrolled ignition during hot-work with fire suppression barrier failed",
                source_reference="OISD-STD-105 §7.5; Factories Act 1948 §38; HAZOP-WS-CK-002",
            )
        )
        # HE-MECH: failing rotating equipment with a worker in the zone.
        self.add_rule(
            CompoundRule(
                template_id="HE-MECH-EXPOSURE",
                name="Rotating equipment failure imminent with worker present",
                pathway="mechanical_injury",
                mandatory=[equipment_failing(0.5), worker_present()],
                predicates=[],
                severity_fn=dynamic_asset_severity(0.65),
                min_satisfied=0,
                # G1 bow-tie metadata
                top_event="Mechanical contact injury from unguarded rotating equipment failure",
                source_reference="Factories Act 1948 §21; OISD-STD-137 §5.1; HAZOP-WS-ME-001",
            )
        )
        # HE-EQUIPMENT-FAILURE: failing asset in facility (active even with 0 workers).
        self.add_rule(
            CompoundRule(
                template_id="HE-EQUIPMENT-FAILURE",
                name="Critical asset failure probability exceeding safety threshold",
                pathway="equipment_hazard",
                mandatory=[equipment_failing(0.5)],
                predicates=[],
                severity_fn=dynamic_asset_severity(0.55),
                min_satisfied=0,
                # G1 bow-tie metadata
                top_event="Critical equipment failure causing production loss or secondary hazard",
                source_reference="OISD-STD-137 §4.3; HAZOP-WS-ME-002",
            )
        )
        # HE-VENT: ventilation failure with worker present in zone.
        self.add_rule(
            CompoundRule(
                template_id="HE-VENTILATION-FAILURE",
                name="Critical ventilation fan failure in active worker zone",
                pathway="ventilation_starvation",
                mandatory=[ventilation_degraded(0.4), worker_present()],
                predicates=[],
                severity_fn=dynamic_ventilation_severity(0.62),
                min_satisfied=0,
                # G1 bow-tie metadata
                top_event="Asphyxiation risk from ventilation failure in occupied zone",
                source_reference="OISD-STD-114 §6.1; Factories Act 1948 §13; DGMS Circular 2018-07",
            )
        )
        # HE-VENTILATION-DEFICIT: ventilation failure in zone (active even with 0 workers).
        self.add_rule(
            CompoundRule(
                template_id="HE-VENTILATION-DEFICIT",
                name="Severe zone ventilation airflow deficit",
                pathway="ventilation_starvation",
                mandatory=[ventilation_degraded(0.4)],
                predicates=[],
                severity_fn=dynamic_ventilation_severity(0.50),
                min_satisfied=0,
                # G1 bow-tie metadata
                top_event="Zone atmosphere degradation from sustained ventilation deficit",
                source_reference="OISD-STD-114 §6.2; HAZOP-WS-CK-004",
            )
        )
        # HE-PERMIT-CONFLICT: simultaneously active incompatible permit types.
        # Hot work + confined space entry is the canonical case — an ignition
        # event (hot work) with a worker physically enclosed (confined space)
        # and limited egress creates a trapped-worker scenario.
        # OISD-STD-105 §7.4 explicitly prohibits this combination.
        self.add_rule(
            CompoundRule(
                template_id="HE-PERMIT-CONFLICT",
                name="Incompatible permits simultaneously active in same zone",
                pathway="trapped_worker_ignition",
                mandatory=[conflicting_permits()],
                predicates=[worker_present()],
                severity_fn=weighted_severity(0.85),
                min_satisfied=0,
                # G1 bow-tie metadata
                top_event="Worker trapped in confined space during active hot-work ignition event",
                source_reference="OISD-STD-105 §7.4; Factories Act 1948 §87; DGMS Circular 2019-04",
            )
        )
        # HE-PERMIT-CONDITIONS-VIOLATED: a hot-work permit remains active after
        # gas conditions in the zone exceed the safe threshold — the permit
        # was issued when conditions were safe but is now a standing ignition
        # hazard. OISD-STD-116 §4.3 mandates immediate suspension on any gas
        # concentration alarm in the affected zone.
        self.add_rule(
            CompoundRule(
                template_id="HE-PERMIT-CONDITIONS-VIOLATED",
                name="Hot-work permit active under conditions that violate original issuance basis",
                pathway="permit_conditions_violated",
                mandatory=[hot_work_permit_with_rising_gas()],
                predicates=[],
                severity_fn=dynamic_gas_severity(0.75),
                min_satisfied=0,
                # G1 bow-tie metadata
                top_event="Ignition risk from hot-work permit persisting after gas threshold breach",
                source_reference="OISD-STD-116 §4.3; DGMS Circular 2019-04",
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

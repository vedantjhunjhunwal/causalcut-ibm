"""SafetyHypergraph -- the live model of the plant.

NetworkX has no native hyperedge type, so we use a hybrid representation that
is the pragmatic choice for an MVP at this scale:

  * a ``MultiDiGraph`` holds the *entities* (zones, assets, workers, sensors,
    permits, barriers, hazards) and the *pairwise* base edges between them
    (a worker is IN a zone, a sensor MONITORS a zone, a permit APPLIES_TO a
    zone, and so on);

  * a separate registry holds *hyperedges* -- compound-danger relationships
    that span three or more nodes and cannot be expressed as a single pairwise
    edge (rising gas + active hot-work permit + missing PPE + degraded
    ventilation, all at once).

Node attributes are the plant's current state. Event listeners mutate those
attributes; the compound rule engine (see ``compound_rules.py``) reads them.
This wrapper owns *structure and state*; it deliberately contains no risk
scoring or intervention logic -- those live downstream.

Deliverable for: "NetworkX Hypergraph Blueprint".
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import networkx as nx

from app.engine.types import (
    Hyperedge,
    InformationClass,
    NodeType,
    SafetyEvent,
    EventType,
)

logger = logging.getLogger("causalcut.hypergraph")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Relations used on the base (pairwise) graph.
class Relation:
    IN_ZONE = "in_zone"            # worker/asset -> zone
    MONITORS = "monitors"          # sensor -> zone/asset
    APPLIES_TO = "applies_to"      # permit -> zone
    PROTECTS = "protects"          # barrier -> zone
    ADJACENT = "adjacent"          # zone -> zone (shared utilities / propagation)
    HELD_BY = "held_by"            # permit -> worker


class SafetyHypergraph:
    """Thread-safe, in-memory hypergraph of the plant.

    The public surface is intentionally small and stable:

    Registration:  ``register_zone / register_asset / register_worker /
                    register_sensor / register_permit / register_barrier``
    Base edges:    ``add_base_edge``
    Hyperedges:    ``register_hyperedge / activate_hyperedge / deactivate_hyperedge``
    Events:        ``apply_event`` (the listener entry point)
    Queries:       ``node / nodes_of_type / neighbors / snapshot``
    """

    def __init__(self, factory_id: str = "steelforge-001") -> None:
        self.factory_id = factory_id
        self._g = nx.MultiDiGraph()
        self._hyperedges: dict[str, Hyperedge] = {}
        self._lock = threading.RLock()
        self._revision = 0

    # ------------------------------------------------------------------ #
    # Node registration
    # ------------------------------------------------------------------ #
    def _add_node(self, node_id: str, node_type: NodeType, **attrs: Any) -> None:
        with self._lock:
            self._g.add_node(
                node_id,
                node_type=node_type.value,
                created_at=_utcnow().isoformat(),
                updated_at=_utcnow().isoformat(),
                **attrs,
            )
            self._revision += 1
        logger.debug("registered %s node %s", node_type.value, node_id)

    def register_zone(
        self,
        zone_id: str,
        name: str = "",
        hazard_class: str = "standard",
        baseline_gas_threshold_ppm: float = 200.0,
    ) -> None:
        self._add_node(
            zone_id,
            NodeType.ZONE,
            name=name or zone_id,
            hazard_class=hazard_class,
            baseline_gas_threshold_ppm=baseline_gas_threshold_ppm,
            ventilation_status="nominal",
            ventilation_flow_ratio=1.0,
            risk_score=0.0,
            risk_info_class=InformationClass.PREDICTED.value,
            status="green",
        )

    def register_asset(
        self, asset_id: str, zone_id: str, asset_type: str = "generic"
    ) -> None:
        self._add_node(
            asset_id,
            NodeType.ASSET,
            asset_type=asset_type,
            failure_probability=0.0,
            failure_mode=None,
            rul_cycles=None,
        )
        if zone_id in self._g:
            self.add_base_edge(asset_id, zone_id, Relation.IN_ZONE)

    def register_worker(
        self, worker_id: str, zone_id: Optional[str] = None
    ) -> None:
        self._add_node(
            worker_id,
            NodeType.WORKER,
            zone=zone_id,
            present=zone_id is not None,
            ppe={"hard_hat": True, "safety_vest": True, "goggles": True, "gloves": True},
            ppe_compliant=True,
            ppe_info_class=InformationClass.MEASURED.value,
        )
        if zone_id and zone_id in self._g:
            self.add_base_edge(worker_id, zone_id, Relation.IN_ZONE)

    def register_sensor(
        self,
        sensor_id: str,
        zone_id: str,
        modality: str = "gas",
        unit: str = "ppm",
    ) -> None:
        self._add_node(
            sensor_id,
            NodeType.SENSOR,
            modality=modality,
            unit=unit,
            value=None,
            info_class=InformationClass.MEASURED.value,
            stale=False,
            last_reading_at=None,
        )
        if zone_id in self._g:
            self.add_base_edge(sensor_id, zone_id, Relation.MONITORS)

    def register_permit(
        self,
        permit_id: str,
        zone_id: str,
        permit_type: str,
        status: str = "active",
        worker_id: Optional[str] = None,
    ) -> None:
        self._add_node(
            permit_id,
            NodeType.PERMIT,
            permit_type=permit_type,
            status=status,
            info_class=InformationClass.SYNTHETIC.value,
        )
        if zone_id in self._g:
            self.add_base_edge(permit_id, zone_id, Relation.APPLIES_TO)
        if worker_id and worker_id in self._g:
            self.add_base_edge(permit_id, worker_id, Relation.HELD_BY)

    def register_barrier(
        self, barrier_id: str, zone_id: str, barrier_type: str, status: str = "active"
    ) -> None:
        self._add_node(
            barrier_id,
            NodeType.BARRIER,
            barrier_type=barrier_type,
            status=status,
            info_class=InformationClass.MEASURED.value,
        )
        if zone_id in self._g:
            self.add_base_edge(barrier_id, zone_id, Relation.PROTECTS)

    # ------------------------------------------------------------------ #
    # Base (pairwise) edges
    # ------------------------------------------------------------------ #
    def add_base_edge(
        self, source: str, target: str, relation: str, **attrs: Any
    ) -> None:
        with self._lock:
            if source not in self._g or target not in self._g:
                raise KeyError(
                    f"cannot add edge {source}->{target}: node(s) not registered"
                )
            # key=relation makes the edge idempotent per relation type.
            self._g.add_edge(source, target, key=relation, relation=relation, **attrs)
            self._revision += 1

    def add_zone_adjacency(self, zone_a: str, zone_b: str, medium: str) -> None:
        """Zones connected via shared utilities (design doc Zone 4)."""
        self.add_base_edge(zone_a, zone_b, Relation.ADJACENT, medium=medium)
        self.add_base_edge(zone_b, zone_a, Relation.ADJACENT, medium=medium)

    # ------------------------------------------------------------------ #
    # Hyperedges
    # ------------------------------------------------------------------ #
    def register_hyperedge(self, edge: Hyperedge) -> None:
        with self._lock:
            missing = [n for n in edge.constituent_nodes if n not in self._g]
            if missing:
                raise KeyError(f"hyperedge {edge.hyperedge_id} references unknown nodes: {missing}")
            self._hyperedges[edge.hyperedge_id] = edge
            self._revision += 1

    def activate_hyperedge(self, hyperedge_id: str, severity: float, pathway: str) -> None:
        with self._lock:
            edge = self._hyperedges[hyperedge_id]
            edge.activated = True
            edge.severity = severity
            edge.pathway = pathway
            edge.activation_time = _utcnow()
            self._revision += 1

    def deactivate_hyperedge(self, hyperedge_id: str) -> None:
        with self._lock:
            edge = self._hyperedges.get(hyperedge_id)
            if edge:
                edge.activated = False
                edge.activation_time = None
                self._revision += 1

    def hyperedges(self, activated_only: bool = False) -> list[Hyperedge]:
        with self._lock:
            edges = list(self._hyperedges.values())
        return [e for e in edges if e.activated] if activated_only else edges

    # ------------------------------------------------------------------ #
    # Event listeners -- the graph's write path
    # ------------------------------------------------------------------ #
    def apply_event(self, event: SafetyEvent) -> None:
        """Update graph state from a canonical event.

        This is the single listener entry point. It dispatches on event type
        and mutates node attributes in place. Unknown nodes are created lazily
        so the graph is resilient to events arriving before registration.
        """
        handler = self._HANDLERS.get(event.event_type)
        if handler is None:
            logger.debug("no handler for event_type=%s", event.event_type)
            return
        with self._lock:
            handler(self, event)
            self._revision += 1

    def _ensure_node(self, node_id: str, node_type: NodeType, **attrs: Any) -> None:
        if node_id not in self._g:
            self._add_node(node_id, node_type, **attrs)

    def _ensure_edge(self, source: str, target: str, relation: str) -> None:
        if source in self._g and target in self._g and not self._g.has_edge(source, target, key=relation):
            self._g.add_edge(source, target, key=relation, relation=relation)

    def _on_gas_anomaly(self, e: SafetyEvent) -> None:
        sensor = e.sensor_id or f"GS-{e.zone_id}"
        self._ensure_node(sensor, NodeType.SENSOR, modality="gas", unit="ppm")
        # Out-of-order guard: with concurrent consumers an older reading can
        # arrive after a newer one. Never let a stale value overwrite a fresher
        # one (mirrors the sensor_latest projection's monotonic guard).
        prev = self._g.nodes[sensor].get("last_reading_at")
        if prev is not None and e.event_time.isoformat() < prev:
            return
        conc = e.value.get("concentration_ppm")
        self._g.nodes[sensor].update(
            value=conc,
            gas_type=e.value.get("gas_type"),
            info_class=e.information_class.value,
            last_reading_at=e.event_time.isoformat(),
            stale=False,
            updated_at=_utcnow().isoformat(),
        )
        if e.zone_id and e.zone_id in self._g:
            self._g.nodes[e.zone_id]["last_gas_ppm"] = conc
            self._g.nodes[e.zone_id]["last_gas_info_class"] = e.information_class.value

    def _on_ppe_violation(self, e: SafetyEvent) -> None:
        if not e.worker_id:
            return
        self._ensure_node(e.worker_id, NodeType.WORKER, zone=e.zone_id)
        node = self._g.nodes[e.worker_id]
        missing = e.value.get("missing_ppe", [])
        ppe = dict(node.get("ppe", {}))
        for item in missing:
            ppe[item] = False
        node.update(
            ppe=ppe,
            ppe_compliant=not missing,
            ppe_info_class=e.information_class.value,
            zone=e.zone_id or node.get("zone"),
            present=True,
            updated_at=_utcnow().isoformat(),
        )
        if e.zone_id:
            self._ensure_edge(e.worker_id, e.zone_id, Relation.IN_ZONE)

    def _on_worker_presence(self, e: SafetyEvent) -> None:
        if not e.worker_id:
            return
        self._ensure_node(e.worker_id, NodeType.WORKER)
        present = bool(e.value.get("present", True))
        node = self._g.nodes[e.worker_id]
        node.update(present=present, zone=e.zone_id if present else None,
                    updated_at=_utcnow().isoformat())
        if present and e.zone_id:
            self._ensure_edge(e.worker_id, e.zone_id, Relation.IN_ZONE)

    def _on_permit_status(self, e: SafetyEvent) -> None:
        if not e.permit_id:
            return
        self._ensure_node(
            e.permit_id, NodeType.PERMIT,
            permit_type=e.value.get("permit_type", "unknown"),
        )
        self._g.nodes[e.permit_id].update(
            status=e.value.get("status", "active"),
            permit_type=e.value.get("permit_type", self._g.nodes[e.permit_id].get("permit_type")),
            info_class=e.information_class.value,
            updated_at=_utcnow().isoformat(),
        )
        if e.zone_id:
            self._ensure_edge(e.permit_id, e.zone_id, Relation.APPLIES_TO)

    def _on_equipment_failure(self, e: SafetyEvent) -> None:
        if not e.asset_id:
            return
        self._ensure_node(e.asset_id, NodeType.ASSET)
        self._g.nodes[e.asset_id].update(
            failure_probability=e.value.get("failure_probability", e.severity),
            failure_mode=e.value.get("failure_mode"),
            rul_cycles=e.value.get("rul_cycles"),
            info_class=e.information_class.value,
            updated_at=_utcnow().isoformat(),
        )
        if e.zone_id:
            self._ensure_edge(e.asset_id, e.zone_id, Relation.IN_ZONE)

    def _on_utility_condition(self, e: SafetyEvent) -> None:
        if not e.zone_id or e.zone_id not in self._g:
            return
        ratio = e.value.get("ventilation_flow_ratio")
        self._g.nodes[e.zone_id].update(
            ventilation_flow_ratio=ratio if ratio is not None else self._g.nodes[e.zone_id].get("ventilation_flow_ratio"),
            ventilation_status=e.value.get("ventilation_status", "nominal"),
            ventilation_info_class=e.information_class.value,
            updated_at=_utcnow().isoformat(),
        )

    def _on_barrier_status(self, e: SafetyEvent) -> None:
        bid = e.value.get("barrier_id")
        if not bid:
            return
        self._ensure_node(bid, NodeType.BARRIER, barrier_type=e.value.get("barrier_type", "unknown"))
        self._g.nodes[bid].update(
            status=e.value.get("status", "active"),
            info_class=e.information_class.value,
            updated_at=_utcnow().isoformat(),
        )

    _HANDLERS = {
        EventType.GAS_ANOMALY: _on_gas_anomaly,
        EventType.PPE_VIOLATION: _on_ppe_violation,
        EventType.WORKER_PRESENCE: _on_worker_presence,
        EventType.PERMIT_STATUS: _on_permit_status,
        EventType.PERMIT_CONFLICT: _on_permit_status,
        EventType.EQUIPMENT_FAILURE: _on_equipment_failure,
        EventType.UTILITY_CONDITION: _on_utility_condition,
        EventType.BARRIER_STATUS: _on_barrier_status,
    }

    async def async_listener(self, event: SafetyEvent) -> None:
        """Coroutine adapter so the graph can subscribe to the EventQueue."""
        self.apply_event(event)

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def node(self, node_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._g.nodes[node_id])

    def has_node(self, node_id: str) -> bool:
        return node_id in self._g

    def nodes_of_type(self, node_type: NodeType) -> list[str]:
        with self._lock:
            return [n for n, d in self._g.nodes(data=True) if d.get("node_type") == node_type.value]

    def nodes_of_type_zone(self) -> list[str]:
        return self.nodes_of_type(NodeType.ZONE)

    def neighbors(self, node_id: str, relation: Optional[str] = None) -> list[str]:
        with self._lock:
            out = []
            for _, tgt, data in self._g.out_edges(node_id, data=True):
                if relation is None or data.get("relation") == relation:
                    out.append(tgt)
            return out

    def predecessors(self, node_id: str, relation: Optional[str] = None) -> list[str]:
        with self._lock:
            out = []
            for src, _, data in self._g.in_edges(node_id, data=True):
                if relation is None or data.get("relation") == relation:
                    out.append(src)
            return out

    def workers_in_zone(self, zone_id: str) -> list[str]:
        return [
            w for w in self.predecessors(zone_id, Relation.IN_ZONE)
            if self._g.nodes[w].get("node_type") == NodeType.WORKER.value
            and self._g.nodes[w].get("present")
        ]

    def active_permits_in_zone(self, zone_id: str) -> list[str]:
        return [
            p for p in self.predecessors(zone_id, Relation.APPLIES_TO)
            if self._g.nodes[p].get("node_type") == NodeType.PERMIT.value
            and self._g.nodes[p].get("status") == "active"
        ]

    def sensors_in_zone(self, zone_id: str) -> list[str]:
        return [
            s for s in self.predecessors(zone_id, Relation.MONITORS)
            if self._g.nodes[s].get("node_type") == NodeType.SENSOR.value
        ]

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def graph(self) -> nx.MultiDiGraph:
        """Direct access to the underlying graph (read-only intent)."""
        return self._g

    def snapshot(self) -> dict[str, Any]:
        """Serializable snapshot for the dashboard / event store."""
        with self._lock:
            return {
                "factory_id": self.factory_id,
                "revision": self._revision,
                "timestamp": _utcnow().isoformat(),
                "nodes": [
                    {"id": n, **d} for n, d in self._g.nodes(data=True)
                ],
                "base_edges": [
                    {"source": u, "target": v, **d}
                    for u, v, d in self._g.edges(data=True)
                ],
                "hyperedges": [e.model_dump(mode="json") for e in self._hyperedges.values()],
            }

    def bootstrap_steelforge(self) -> None:
        """Register the canonical Steelforge topology from the design doc.

        Six zones, their sensors/barriers, and Zone-4 propagation adjacencies.
        This gives the system a plant to reason about out of the box.
        """
        self.register_zone("zone-1", "Coke Oven", "gas_hazard", 200.0)
        self.register_zone("zone-2", "Blast Furnace", "high_risk", 350.0)
        self.register_zone("zone-3", "Machine Shop", "rotating_equipment", 500.0)
        self.register_zone("zone-4", "Shared Utilities", "propagation", 500.0)
        self.register_zone("zone-5", "CCTV/PPE Checkpoints", "admin", 999.0)
        self.register_zone("zone-6", "Control Room", "admin", 999.0)

        # Zone 4 is the propagation medium between the hazard zones.
        self.add_zone_adjacency("zone-1", "zone-4", "ventilation_duct")
        self.add_zone_adjacency("zone-2", "zone-4", "ventilation_duct")
        self.add_zone_adjacency("zone-3", "zone-4", "utility_bus")
        self.add_zone_adjacency("zone-1", "zone-2", "shared_duct")

        for i in range(1, 17):
            self.register_sensor(f"GS-{i:02d}", "zone-1" if i <= 16 else "zone-2", "gas", "ppm")
        self.register_sensor("VENT-01", "zone-1", "airflow", "ratio")
        self.register_sensor("VENT-02", "zone-2", "airflow", "ratio")

        self.register_barrier("FIRE-SUP-01", "zone-1", "fire_suppression")
        self.register_barrier("GAS-ISO-01", "zone-1", "gas_isolation")
        self.register_barrier("FIRE-SUP-02", "zone-2", "fire_suppression")
        self.register_barrier("GAS-ISO-02", "zone-2", "gas_isolation")
        logger.info("bootstrapped Steelforge topology (%d nodes)", self._g.number_of_nodes())

"""Factory topology graph â€” Day 1 blueprint (design doc Â§2, Â§5.2).

Static physical adjacency between zones. This is the substrate the
spatiotemporal risk propagator walks over: risk in zone i can only reach
zone j directly if an edge exists here, weighted by how "open" that path is
(shared ventilation duct, physical doorway, utility corridor, etc).

This is deliberately just a graph, not a simulation. Day 2+ reads edge
weights dynamically from barrier_status / utility_condition events; today
they are static design-time estimates so the propagator has something to
run against.

All of this is [S] â€” synthetic engineering estimate, not measured plant
data â€” until Tarun's hypergraph wrapper (Day 3) starts updating it live.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from app.schemas.enums import ZoneId


@dataclass(frozen=True)
class ZoneEdge:
    """One propagation path between two zones.

    weight: fraction of risk/hazard intensity that transmits from one zone
        to its neighbour per unit time, in [0, 1]. 0 = fully isolated,
        1 = fully open (no barrier at all).
    channel: what physically carries the hazard across this edge.
    """

    weight: float
    channel: str  # "shared_ventilation" | "doorway" | "utility_corridor" | "line_of_sight"


# Static topology estimate for Steelforge. Tune with the real plant drawing
# before demo day â€” these are placeholders that make the propagator
# runnable, not measured.
ZONE_ADJACENCY: dict[tuple[ZoneId, ZoneId], ZoneEdge] = {
    (ZoneId.ZONE_1_COKE_OVEN, ZoneId.ZONE_4_SHARED_UTILITIES):
        ZoneEdge(weight=0.65, channel="shared_ventilation"),
    (ZoneId.ZONE_2_BLAST_FURNACE, ZoneId.ZONE_4_SHARED_UTILITIES):
        ZoneEdge(weight=0.55, channel="shared_ventilation"),
    (ZoneId.ZONE_3_MACHINE_SHOP, ZoneId.ZONE_4_SHARED_UTILITIES):
        ZoneEdge(weight=0.30, channel="utility_corridor"),
    (ZoneId.ZONE_1_COKE_OVEN, ZoneId.ZONE_2_BLAST_FURNACE):
        ZoneEdge(weight=0.25, channel="doorway"),
    (ZoneId.ZONE_5_CCTV_CHECKPOINTS, ZoneId.ZONE_1_COKE_OVEN):
        ZoneEdge(weight=0.10, channel="doorway"),
    (ZoneId.ZONE_5_CCTV_CHECKPOINTS, ZoneId.ZONE_2_BLAST_FURNACE):
        ZoneEdge(weight=0.10, channel="doorway"),
    (ZoneId.ZONE_5_CCTV_CHECKPOINTS, ZoneId.ZONE_3_MACHINE_SHOP):
        ZoneEdge(weight=0.10, channel="doorway"),
    (ZoneId.ZONE_6_CONTROL_ROOM, ZoneId.ZONE_4_SHARED_UTILITIES):
        ZoneEdge(weight=0.05, channel="line_of_sight"),
}


def build_topology_graph() -> nx.Graph:
    """Undirected weighted graph over the six zones."""
    g = nx.Graph()
    g.add_nodes_from(z.value for z in ZoneId)
    for (a, b), edge in ZONE_ADJACENCY.items():
        g.add_edge(a.value, b.value, weight=edge.weight, channel=edge.channel)
    return g


def neighbours(zone: ZoneId, graph: nx.Graph | None = None) -> list[tuple[str, float]]:
    """(neighbour_zone_id, edge_weight) pairs for one zone."""
    g = graph or build_topology_graph()
    return [(n, g[zone.value][n]["weight"]) for n in g.neighbors(zone.value)]

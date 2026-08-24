import React from "react";
import FactoryMap from "./FactoryMap";

// Default Steelforge zone layout — shown before any scenario/graph data loads.
// Zone IDs must match the STEELFORGE_LAYOUT keys in FactoryMap.jsx so the
// hardcoded coordinates are used and the map is always visible.
const DEFAULT_ZONES = [
  { zone_id: "zone-1", name: "Coke Oven",           hazard_class: "gas_hazard" },
  { zone_id: "zone-2", name: "Blast Furnace",       hazard_class: "high_risk" },
  { zone_id: "zone-3", name: "Machine Shop",        hazard_class: "standard" },
  { zone_id: "zone-4", name: "Shared Utilities",    hazard_class: "propagation" },
  { zone_id: "zone-5", name: "CCTV/PPE Checkpoints",hazard_class: "standard" },
  { zone_id: "zone-6", name: "Control Room",        hazard_class: "standard" },
];

export default function FactoryMapView({
  zoneRisk = {},
  graph = { nodes: [], edges: [] },
  scenario,
  causalPaths = [],
  interventions = [],
  activatedRules = []
}) {
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];

  // Prefer graph nodes > scenario zones > hardcoded default layout
  const graphZones = nodes.filter((n) => n.type === "zone");
  const scenarioZones = scenario?.zones || [];
  const zones = graphZones.length > 0
    ? graphZones
    : scenarioZones.length > 0
      ? scenarioZones
      : DEFAULT_ZONES;

  const graphSensors = nodes.filter((n) => n.type === "sensor");
  const sensors = graphSensors.length > 0 ? graphSensors : (scenario?.sensors || []);

  const graphWorkers = nodes.filter((n) => n.type === "worker");
  const workers = graphWorkers.length > 0 ? graphWorkers : (scenario?.workers || []);

  const graphAssets = nodes.filter((n) => n.type === "asset");
  const assets = graphAssets.length > 0 ? graphAssets : (scenario?.assets || []);

  const graphPermits = nodes.filter((n) => n.type === "permit");
  const permits = graphPermits.length > 0 ? graphPermits : (scenario?.permits || []);

  // Extract rules from graph nodes if any
  const rules = nodes.filter((n) => n.type === "rule");
  // Merge with activatedRules prop if provided separately
  const allRules = [...rules, ...activatedRules].reduce((acc, rule) => {
    if (!acc.find(r => r.id === rule.id)) {
      acc.push(rule);
    }
    return acc;
  }, []);

  const causalEdges = edges.filter((e) => e.causal === true);

  return (
    <div className="panel-box" style={{ padding: 20 }}>
      <div className="panel-header-row" style={{ marginBottom: 14 }}>
        <div>
          <span className="panel-title-text">FACTORY SPATIAL RISK MAP</span>
          <span className="panel-meta-text" style={{ marginLeft: 12 }}>
            DYNAMIC ENTITY GRAPH RENDERING
          </span>
        </div>
      </div>
      <FactoryMap
        zones={zones}
        sensors={sensors}
        workers={workers}
        assets={assets}
        permits={permits}
        riskLevels={zoneRisk}
        causalPaths={causalEdges}
        interventions={interventions}
        activatedRules={allRules}
      />
    </div>
  );
}

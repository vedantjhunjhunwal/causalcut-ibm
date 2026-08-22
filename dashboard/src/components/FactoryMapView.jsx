import React from "react";
import FactoryMap from "./FactoryMap";

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

  // Fallback to scenario data if graph has not run yet
  const graphZones = nodes.filter((n) => n.type === "zone");
  const zones = graphZones.length > 0 ? graphZones : (scenario?.zones || []);
  
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

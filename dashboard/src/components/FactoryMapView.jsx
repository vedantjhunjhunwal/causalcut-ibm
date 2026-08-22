import React, { useMemo } from "react";
import FactoryMap from "./FactoryMap";

const OLD_ZONE_TO_LOGICAL = {
  "zone-1": "Coke Oven",
  "zone-2": "Battery 3",
  "zone-3": "Gas Treatment",
  "zone-4": "Break Room",
  "zone-5": "Quench Tower",
  "zone-6": "Control Room",
};

export default function FactoryMapView({ zoneRisk = {}, graph }) {
  // Convert zoneRisk and graph workers into the `entities` array format for FactoryMap
  const entities = useMemo(() => {
    const list = [];
    
    // Process risks
    Object.entries(zoneRisk).forEach(([zoneId, risk]) => {
      const logicalZone = OLD_ZONE_TO_LOGICAL[zoneId] || "Coke Oven";
      let signal = "LOW";
      if (risk >= 0.6) signal = "HIGH";
      else if (risk >= 0.3) signal = "MEDIUM";

      if (signal !== "LOW") {
        list.push({
          zone: logicalZone,
          entity: "Aggregated Zone Risk",
          state: `Risk: ${risk.toFixed(2)}`,
          signal,
        });
      }
    });

    // Process workers from graph
    if (graph && graph.nodes) {
      graph.nodes.forEach(n => {
        if (n.type === "worker" && n.metadata?.zone) {
          const zoneId = n.metadata.zone;
          const logicalZone = OLD_ZONE_TO_LOGICAL[zoneId] || "Coke Oven";
          const isViolating = n.metadata?.ppe_compliant === false;
          list.push({
            zone: logicalZone,
            entity: `Worker ${n.id}`,
            state: isViolating ? "PPE Violation" : "Compliant",
            signal: isViolating ? "HIGH" : "LOW",
          });
        }
      });
    }

    return list;
  }, [zoneRisk, graph]);

  return (
    <div className="panel-box" style={{ padding: 20, marginBottom: 20 }}>
      <div className="panel-header-row" style={{ marginBottom: 12 }}>
        <div>
          <span className="panel-title-text">FACTORY SPATIAL MAP</span>
          <span className="panel-meta-text" style={{ marginLeft: 12 }}>
            REAL-TIME ZONE RISK HIGHLIGHTS & WORKER TRACKING
          </span>
        </div>
      </div>
      
      {/* Replaced the old "potato" map with the new FactoryMap component */}
      <FactoryMap entities={entities} />
    </div>
  );
}

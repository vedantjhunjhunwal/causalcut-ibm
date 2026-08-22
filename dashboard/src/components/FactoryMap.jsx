import React, { useState } from "react";

// Maps the dataset's logical zones to our visual SVG zones
const zoneMapping = {
  "Gas Treatment": "zone-gas-storage",
  "Coke Oven": "zone-cnc-machining",
  "Battery 3": "zone-hydraulic-press",
  "Quench Tower": "zone-ppe-checkpoint",
  "Coal Handling": "zone-main-entrance",
  "Control Room": "zone-control-room",
  "Break Room": "zone-break-room",
};

const visualZones = [
  { id: "zone-control-room", name: "Control Room" },
  { id: "zone-gas-storage", name: "Gas / Chem Storage" },
  { id: "zone-cnc-machining", name: "CNC Machining Floor" },
  { id: "zone-hydraulic-press", name: "Hydraulic Press Bay" },
  { id: "zone-break-room", name: "Break Room" },
  { id: "zone-ppe-checkpoint", name: "PPE Checkpoint" },
  { id: "zone-main-entrance", name: "Main Entrance" },
];

export default function FactoryMap({ entities = [] }) {
  const [hoveredZone, setHoveredZone] = useState(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  // Aggregate signals per visual zone
  const zoneStates = {};
  const zoneEntities = {};

  visualZones.forEach((vz) => {
    zoneStates[vz.id] = "LOW";
    zoneEntities[vz.id] = [];
  });

  entities.forEach((ent) => {
    const visualId = zoneMapping[ent.zone] || "zone-control-room"; // Fallback to safe zone if unknown
    
    if (!zoneEntities[visualId]) {
       zoneEntities[visualId] = [];
       zoneStates[visualId] = "LOW";
    }
    
    zoneEntities[visualId].push(ent);

    // Escalating state logic
    const currState = zoneStates[visualId];
    if (ent.signal === "HIGH") {
      zoneStates[visualId] = "HIGH";
    } else if (ent.signal === "MEDIUM" && currState !== "HIGH") {
      zoneStates[visualId] = "MEDIUM";
    }
  });

  const getZoneClass = (id) => {
    const signal = zoneStates[id];
    if (signal === "HIGH") return "zone state-critical";
    if (signal === "MEDIUM") return "zone state-elevated";
    return "zone state-safe";
  };

  const handleMouseMove = (e, visualId) => {
    setHoveredZone(visualId);
    setMousePos({ x: e.clientX, y: e.clientY });
  };

  const handleMouseLeave = () => {
    setHoveredZone(null);
  };

  return (
    <div className="factory-map-container" style={{ position: "relative", width: "100%", maxWidth: "800px", margin: "0 auto 24px auto" }}>
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 800" width="100%" height="100%" style={{ background: "#0f111a", borderRadius: "16px", border: "1px solid #1e293b" }}>
        <defs>
          <pattern id="hatch-safe" width="12" height="12" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <line x1="0" y1="0" x2="0" y2="12" className="gas-hatch" />
          </pattern>
        </defs>

        {/* Background / Base Shell */}
        <rect className="facility-shell" x="30" y="30" width="940" height="740" />

        {/* ======================= */}
        {/*        ZONES            */}
        {/* ======================= */}
        <g id="zones">
          {/* 1. Control Room */}
          <g id="zone-control-room" onMouseMove={(e) => handleMouseMove(e, "zone-control-room")} onMouseLeave={handleMouseLeave} style={{ cursor: "crosshair" }}>
            <rect className={getZoneClass("zone-control-room")} x="70" y="70" width="250" height="140" />
            <rect className="door" x="315" y="120" width="10" height="40" />
            <text x="90" y="105" className="map-text-label">Control Room</text>
            <text x="90" y="125" className="map-text-sub">MANAGER STATION</text>
            <rect className="machine" x="90" y="145" width="120" height="40" rx="4" />
          </g>

          {/* 2. Gas & Chemical Storage */}
          <g id="zone-gas-storage" onMouseMove={(e) => handleMouseMove(e, "zone-gas-storage")} onMouseLeave={handleMouseLeave} style={{ cursor: "crosshair" }}>
            <rect className={getZoneClass("zone-gas-storage")} x="680" y="70" width="250" height="140" />
            <rect x="680" y="70" width="250" height="140" fill="url(#hatch-safe)" rx="12" style={{ pointerEvents: "none" }} />
            <rect className="door" x="675" y="120" width="10" height="40" />
            <text x="700" y="105" className="map-text-label">Gas Treatment Facility</text>
            <text x="700" y="125" className="map-text-sub">LEAK CLASSIFIER</text>
            <circle cx="740" cy="165" r="20" className="machine" />
            <circle cx="800" cy="165" r="20" className="machine" />
            <circle cx="860" cy="165" r="20" className="machine" />
          </g>

          {/* 3. CNC Machining Floor */}
          <g id="zone-cnc-machining" onMouseMove={(e) => handleMouseMove(e, "zone-cnc-machining")} onMouseLeave={handleMouseLeave} style={{ cursor: "crosshair" }}>
            <rect className={getZoneClass("zone-cnc-machining")} x="70" y="250" width="250" height="410" />
            <rect className="door" x="315" y="300" width="10" height="50" />
            <text x="90" y="285" className="map-text-label">Coke Oven Battery</text>
            <text x="90" y="305" className="map-text-sub">ASSET CLASSIFIER</text>
            <rect className="machine" x="100" y="340" width="60" height="80" />
            <rect className="machine" x="100" y="450" width="60" height="80" />
            <rect className="machine" x="100" y="560" width="60" height="80" />
            <rect className="machine" x="220" y="340" width="60" height="80" />
            <rect className="machine" x="220" y="500" width="60" height="80" />
          </g>

          {/* 4. Hydraulic Press Bay */}
          <g id="zone-hydraulic-press" onMouseMove={(e) => handleMouseMove(e, "zone-hydraulic-press")} onMouseLeave={handleMouseLeave} style={{ cursor: "crosshair" }}>
            <rect className={getZoneClass("zone-hydraulic-press")} x="680" y="250" width="250" height="230" />
            <rect className="door" x="675" y="300" width="10" height="50" />
            <text x="700" y="285" className="map-text-label">Blast Furnace</text>
            <text x="700" y="305" className="map-text-sub">FAULT CLASSIFIER</text>
            <rect className="machine" x="720" y="340" width="80" height="50" />
            <rect className="machine" x="720" y="410" width="80" height="50" />
          </g>

          {/* 5. Break Room */}
          <g id="zone-break-room" onMouseMove={(e) => handleMouseMove(e, "zone-break-room")} onMouseLeave={handleMouseLeave} style={{ cursor: "crosshair" }}>
            <rect className={getZoneClass("zone-break-room")} x="680" y="520" width="250" height="190" />
            <rect className="door" x="675" y="610" width="10" height="40" />
            <text x="700" y="555" className="map-text-label">Shared Utilities</text>
            <text x="700" y="575" className="map-text-sub">LOW-RISK ZONE</text>
            <rect className="machine" x="730" y="600" width="120" height="60" rx="30" />
          </g>

          {/* 6. PPE Checkpoint */}
          <g id="zone-ppe-checkpoint" onMouseMove={(e) => handleMouseMove(e, "zone-ppe-checkpoint")} onMouseLeave={handleMouseLeave} style={{ cursor: "crosshair" }}>
            <rect className={getZoneClass("zone-ppe-checkpoint")} x="320" y="520" width="360" height="80" />
            <rect className="door" x="460" y="515" width="80" height="10" />
            <rect className="door" x="460" y="595" width="80" height="10" />
            <text x="500" y="545" className="map-text-label" textAnchor="middle">Quench Tower</text>
            <text x="500" y="565" className="map-text-sub" textAnchor="middle">PPE & SAFETY CHECKPOINT</text>
            <rect className="machine" x="360" y="575" width="80" height="15" />
            <rect className="machine" x="560" y="575" width="80" height="15" />
          </g>

          {/* 7. Main Entrance */}
          <g id="zone-main-entrance" onMouseMove={(e) => handleMouseMove(e, "zone-main-entrance")} onMouseLeave={handleMouseLeave} style={{ cursor: "crosshair" }}>
            <rect className={getZoneClass("zone-main-entrance")} x="380" y="660" width="240" height="80" />
            <rect className="door" x="460" y="735" width="80" height="10" />
            <text x="500" y="700" className="map-text-label" textAnchor="middle">Coal Handling</text>
            <text x="500" y="720" className="map-text-sub" textAnchor="middle">MAIN LOBBY / EXIT</text>
          </g>
        </g>

        {/* ======================= */}
        {/*   OCCUPANCY AVATARS     */}
        {/* ======================= */}
        <g id="occupancy-avatars" style={{ pointerEvents: "none" }}>
          {/* CNC Floor */}
          <rect className="avatar-body" x="180" y="370" width="14" height="24" rx="7" />
          <rect className="avatar-body" x="180" y="480" width="14" height="24" rx="7" />
          
          {/* Hydraulic Press */}
          <rect className="avatar-body" x="820" y="350" width="14" height="24" rx="7" />
          <rect className="avatar-body" x="820" y="420" width="14" height="24" rx="7" />
          
          {/* Control Room */}
          <rect className="avatar-body" x="130" y="130" width="14" height="24" rx="7" />
          <rect className="avatar-body" x="170" y="130" width="14" height="24" rx="7" />
          
          {/* Break Room */}
          <rect className="avatar-body" x="710" y="618" width="14" height="24" rx="7" />
          <rect className="avatar-body" x="760" y="570" width="14" height="24" rx="7" />
        </g>

        {/* ======================= */}
        {/*     SENSOR NODES        */}
        {/* ======================= */}
        <g id="sensor-nodes" style={{ pointerEvents: "none" }}>
          <g transform="translate(130, 320)"><circle className="sensor-ring" r="10" /><circle className="sensor-core" r="4" /></g>
          <g transform="translate(250, 320)"><circle className="sensor-ring" r="10" /><circle className="sensor-core" r="4" /></g>
          <g transform="translate(760, 325)"><circle className="sensor-ring" r="10" /><circle className="sensor-core" r="4" /></g>
          <g transform="translate(740, 150)"><circle className="sensor-ring" r="10" /><circle className="sensor-core" r="4" /></g>
          <g transform="translate(800, 150)"><circle className="sensor-ring" r="10" /><circle className="sensor-core" r="4" /></g>
        </g>
      </svg>

      {/* Hover Tooltip Overlay */}
      {hoveredZone && (
        <div
          className="map-tooltip"
          style={{
            left: mousePos.x + 15,
            top: mousePos.y + 15,
          }}
        >
          <div className="tooltip-title">{visualZones.find(z => z.id === hoveredZone)?.name}</div>
          <div className="tooltip-body">
            {zoneEntities[hoveredZone] && zoneEntities[hoveredZone].length > 0 ? (
              <ul className="tooltip-list">
                {zoneEntities[hoveredZone].map((ent, idx) => (
                  <li key={idx} className="tooltip-item">
                    <span className={`badge-pill ${ent.signal.toLowerCase()} tooltip-badge`}>●</span>
                    <div className="tooltip-ent-text">
                      <div className="ent-name">{ent.entity}</div>
                      <div className="ent-state">{ent.state}</div>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="tooltip-empty">No active sensors or operations reported.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

import React, { useState } from "react";
import { GitBranch, ShieldAlert, ChevronRight, Activity, Zap } from "lucide-react";
import HypergraphView from "../HypergraphView";

export default function RiskPathsView({ result, onNavigate }) {
  const [selectedPath, setSelectedPath] = useState("RP-2047");

  const riskPaths = [
    {
      id: "RP-2047",
      rootZone: "Gas Treatment",
      pathway: "Gas Accumulation & Vapor Cloud Flash Fire",
      severity: 0.74,
      likelihood: 0.81,
      targetZone: "Battery 3",
      propagationZones: ["Gas Treatment", "Battery 3", "Quench Tower"],
      factors: [
        "G-204 Methane Sensor (74 ppm > 50 ppm limit)",
        "Degraded scrubber ventilation flow ratio (0.65)",
        "Active Hot Work Permit HW-8821 in adjacent Battery 3",
        "2 workers present on Scrubber Platform deck",
      ],
      interventions: ["Isolate Gas Line G-204", "Pause HW-8821", "Evacuate Platform"],
    },
    {
      id: "RP-2039",
      rootZone: "Coke Oven",
      pathway: "High-Pressure Hydraulic Seal Breach",
      severity: 0.48,
      likelihood: 0.52,
      targetZone: "Coal Handling",
      propagationZones: ["Coke Oven", "Coal Handling"],
      factors: [
        "Pressure Train A valve fluctuation (1.02 bar nominal)",
        "Conveyor CH-04 motor thermal rise (+8°C)",
      ],
      interventions: ["Boost Ventilation Train A", "Inspect Seal A-2"],
    },
  ];

  const sampleGraph = result?.graph || {
    nodes: [
      { id: "zone-gas", label: "Gas Treatment", type: "zone", status: "critical", risk: 0.74 },
      { id: "zone-battery", label: "Battery 3", type: "zone", status: "warning", risk: 0.58 },
      { id: "zone-oven", label: "Coke Oven", type: "zone", status: "normal", risk: 0.12 },
      { id: "GS-03", label: "G-204 Gas Sensor (74 ppm)", type: "sensor", status: "critical" },
      { id: "HW-8821", label: "Permit HW-8821 (Hot Work)", type: "permit", status: "warning" },
      { id: "W-001", label: "Worker W-001", type: "worker", status: "normal" },
      { id: "W-002", label: "Worker W-002", type: "worker", status: "warning" },
    ],
    edges: [
      { id: "e1", source: "GS-03", target: "zone-gas", label: "gas spike" },
      { id: "e2", source: "zone-gas", target: "zone-battery", label: "vapor migration" },
      { id: "e3", source: "HW-8821", target: "zone-battery", label: "ignition source" },
      { id: "e4", source: "W-002", target: "zone-gas", label: "exposure" },
    ],
    hyperedges: [
      {
        id: "H-01",
        label: "Flash Fire Compound Risk",
        severity: 0.74,
        nodes: ["GS-03", "zone-gas", "HW-8821", "zone-battery"],
      },
    ],
  };

  const currentPath = riskPaths.find((p) => p.id === selectedPath) || riskPaths[0];

  return (
    <div className="page-canvas">
      <div className="page-header">
        <div>
          <div className="breadcrumbs">COMMAND / CAUSAL RISK PATHWAYS</div>
          <h1 className="page-title">Active Risk Paths</h1>
          <div className="page-subtitle">
            Causal propagation chains traced from live sensor anomalies to potential harm.
          </div>
        </div>
        <button className="action-btn primary" onClick={() => onNavigate("interventions")}>
          Review Interventions →
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.6fr", gap: 20, alignItems: "start", marginBottom: 20 }}>
        {/* Left: Risk Paths List */}
        <div className="panel-box">
          <div className="panel-header-row">
            <span className="panel-title-text">DETECTED PATHWAYS · 2 ACTIVE</span>
            <GitBranch size={14} color="#64748b" />
          </div>

          <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 10 }}>
            {riskPaths.map((p) => {
              const isSelected = selectedPath === p.id;
              return (
                <div
                  key={p.id}
                  className={`rec-card ${isSelected ? "selected" : ""}`}
                  onClick={() => setSelectedPath(p.id)}
                >
                  <div className="rec-code">{p.id} · Origin: {p.rootZone}</div>
                  <div className="rec-title-row">
                    <span className="rec-name" style={{ fontSize: 13 }}>{p.pathway}</span>
                    <span className={`badge-pill ${p.severity > 0.6 ? "high" : "medium"}`}>
                      ● {(p.severity * 10).toFixed(1)} / 10
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                    Propagates to: <b>{p.propagationZones.join(" → ")}</b>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: Pathway Detail */}
        <div className="panel-box" style={{ padding: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <span className="badge-pill high">● HIGH SEVERITY ({currentPath.severity})</span>
            <span className="mono" style={{ fontSize: 11, color: "#64748b" }}>
              Likelihood {currentPath.likelihood}
            </span>
          </div>

          <h3 style={{ margin: "0 0 8px 0", fontSize: 17, fontWeight: 700 }}>
            {currentPath.pathway}
          </h3>
          <div style={{ fontSize: 12, color: "#475569", marginBottom: 16 }}>
            Origin Zone: <b>{currentPath.rootZone}</b> → Target Zone: <b>{currentPath.targetZone}</b>
          </div>

          <div style={{ marginBottom: 16 }}>
            <div className="kpi-title" style={{ marginBottom: 6 }}>CONTRIBUTING HAZARD FACTORS</div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.6, color: "#1e293b" }}>
              {currentPath.factors.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>

          <div>
            <div className="kpi-title" style={{ marginBottom: 6 }}>RECOMMENDED CUT ACTIONS</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {currentPath.interventions.map((iv, i) => (
                <span
                  key={i}
                  style={{
                    backgroundColor: "#fef3c7",
                    border: "1px solid #fcd34d",
                    color: "#92400e",
                    padding: "4px 10px",
                    borderRadius: 4,
                    fontSize: 11.5,
                    fontWeight: 600,
                  }}
                >
                  ⚡ {iv}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Interactive Hypergraph Component */}
      <HypergraphView graph={sampleGraph} />
    </div>
  );
}

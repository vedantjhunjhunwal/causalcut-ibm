import React, { useState } from "react";
import { GitBranch, ShieldAlert, ChevronRight, Activity, Zap } from "lucide-react";
import HypergraphView from "../HypergraphView";

export default function RiskPathsView({ result, onNavigate }) {
  const [selectedPath, setSelectedPath] = useState("RP-2047");

  const riskPaths = result?.causal_paths || [];

  const sampleGraph = result?.graph || {
    nodes: [],
    edges: [],
    hyperedges: [],
  };

  const currentPath = riskPaths.find((p) => (p.id || p.hyperedge_id) === selectedPath) || riskPaths[0] || null;

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
              const pId = p.id || p.hyperedge_id;
              const isSelected = selectedPath === pId;
              return (
                <div
                  key={pId}
                  className={`rec-card ${isSelected ? "selected" : ""}`}
                  onClick={() => setSelectedPath(pId)}
                >
                  <div className="rec-code">{pId} · Origin: {p.root_zone || p.rootZone}</div>
                  <div className="rec-title-row">
                    <span className="rec-name" style={{ fontSize: 13 }}>{p.pathway}</span>
                    <span className={`badge-pill ${p.severity > 0.6 ? "high" : "medium"}`}>
                      ● {(p.severity * 10).toFixed(1)} / 10
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                    Propagates to: <b>{(p.propagation_zones || p.propagationZones || []).join(" → ")}</b>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: Pathway Detail */}
        <div className="panel-box" style={{ padding: 20 }}>
          {currentPath ? (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <span className="badge-pill high">● HIGH SEVERITY ({currentPath.severity})</span>
                <span className="mono" style={{ fontSize: 11, color: "#64748b" }}>
                  Likelihood {currentPath.likelihood || "N/A"}
                </span>
              </div>

              <h3 style={{ margin: "0 0 8px 0", fontSize: 17, fontWeight: 700 }}>
                {currentPath.pathway}
              </h3>
              <div style={{ fontSize: 12, color: "#475569", marginBottom: 16 }}>
                Origin Zone: <b>{currentPath.root_zone || currentPath.rootZone}</b> → Target Zone: <b>{(currentPath.propagation_zones || currentPath.propagationZones || []).join(", ") || "None"}</b>
              </div>

              <div style={{ marginBottom: 16 }}>
                <div className="kpi-title" style={{ marginBottom: 6 }}>CONTRIBUTING HAZARD FACTORS</div>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.6, color: "#1e293b" }}>
                  {(currentPath.contributing_factors || currentPath.factors || []).map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              </div>

              <div>
                <div className="kpi-title" style={{ marginBottom: 6 }}>RECOMMENDED CUT ACTIONS</div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {(currentPath.candidate_interventions || currentPath.interventions || []).map((iv, i) => (
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
                      ⚡ {iv.action || iv}
                    </span>
                  ))}
                </div>
              </div>
            </>
          ) : (
            <div style={{ textAlign: "center", padding: "40px 0", color: "#64748b" }}>
              No active risk paths detected.
            </div>
          )}
        </div>
      </div>

      {/* Interactive Hypergraph Component */}
      <HypergraphView graph={sampleGraph} />
    </div>
  );
}

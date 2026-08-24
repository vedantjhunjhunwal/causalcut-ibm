import React, { useState } from "react";
import { Settings, User, Key, Sliders, Building } from "lucide-react";

export default function SettingsView({ operator, setOperator, facility, setFacility = () => {} }) {
  const [apiKey, setApiKey] = useState("dev-key-so-a");
  const [threshold, setThreshold] = useState(0.15);
  const [saved, setSaved] = useState(false);

  const operators = [
    { name: "N. Sharma", role: "SHIFT OFFICER · B", initials: "NS" },
    { name: "M. Rao", role: "SAFETY SPECIALIST", initials: "MR" },
    { name: "A. Verma", role: "PLANT CONTROLLER", initials: "AV" },
  ];

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  return (
    <div className="page-canvas">
      <div className="page-header">
        <div>
          <div className="breadcrumbs">SYSTEM / PLATFORM CONFIGURATION</div>
          <h1 className="page-title">Settings & Governance Control</h1>
          <div className="page-subtitle">
            Facility parameters, operator role authentication, and threshold safeguards.
          </div>
        </div>
        <button className="action-btn primary" onClick={handleSave}>
          Save Settings
        </button>
      </div>

      {saved && (
        <div style={{ padding: "10px 16px", backgroundColor: "#ecfdf5", color: "#047857", borderRadius: 4, marginBottom: 16, fontSize: 12.5, fontWeight: 600, border: "1px solid #a7f3d0" }}>
          ✓ Configuration successfully updated and synchronized.
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {/* Operator Persona */}
        <div className="panel-box" style={{ padding: 20 }}>
          <div className="panel-title-text" style={{ marginBottom: 14, display: "flex", alignItems: "center", gap: 8 }}>
            <User size={16} />
            <span>Active Operator Persona</span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {operators.map((op) => (
              <div
                key={op.name}
                className={`rec-card ${operator.name === op.name ? "selected" : ""}`}
                onClick={() => setOperator(op)}
                style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px" }}
              >
                <div className="user-avatar">{op.initials}</div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>{op.name}</div>
                  <div style={{ fontSize: 10.5, color: "#64748b" }}>{op.role}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Facility & Safety Safeguards */}
        <div className="panel-box" style={{ padding: 20 }}>
          <div className="panel-title-text" style={{ marginBottom: 14, display: "flex", alignItems: "center", gap: 8 }}>
            <Building size={16} />
            <span>Active Facility Context</span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase", display: "block", marginBottom: 6 }}>
                Facility Name
              </label>
              <input
                style={{ width: "100%", padding: "8px 12px", borderRadius: 4, border: "1px solid #cbd5e1", fontSize: 13 }}
                value={facility}
                onChange={(e) => setFacility(e.target.value)}
              />
            </div>

            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase", display: "block", marginBottom: 6 }}>
                Operator API Key (X-API-Key)
              </label>
              <input
                style={{ width: "100%", padding: "8px 12px", borderRadius: 4, border: "1px solid #cbd5e1", fontSize: 13, fontFamily: "var(--font-mono)" }}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </div>

            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase", display: "block", marginBottom: 6 }}>
                Safety Cut Threshold ({threshold})
              </label>
              <input
                type="range"
                min="0.05"
                max="0.50"
                step="0.01"
                style={{ width: "100%" }}
                value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value))}
              />
              <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                Interventions will target reducing residual risk below {threshold}.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

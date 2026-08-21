import React, { useEffect, useState } from "react";
import { api } from "../api";
import { Cpu, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";

export default function ModelStatus() {
  const [models, setModels] = useState(null);

  useEffect(() => {
    let alive = true;
    const fetchStatus = async () => {
      try {
        const data = await api.modelStatus();
        if (alive && data) setModels(data);
      } catch (e) {
        // backend may be starting
      }
    };
    fetchStatus();
    const t = setInterval(fetchStatus, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (!models) {
    return (
      <div className="panel-box" style={{ padding: 16 }}>
        <div className="panel-header-row" style={{ marginBottom: 8 }}>
          <span className="panel-title-text">MODEL REGISTRY STATUS</span>
          <Cpu size={14} color="#94a3b8" />
        </div>
        <div style={{ fontSize: 11.5, color: "#64748b" }}>Connecting to model servers…</div>
      </div>
    );
  }

  const entries = Object.entries(models).filter(([k]) => k !== "execution_mode");

  return (
    <div className="panel-box" style={{ padding: 16 }}>
      <div className="panel-header-row" style={{ marginBottom: 12 }}>
        <span className="panel-title-text">MODEL REGISTRY STATUS</span>
        <span className="badge-pill connected">● LIVE</span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {entries.map(([name, info]) => {
          const isReal = info.available === true && !info.degraded_reason;
          const isDegraded = !!info.degraded_reason;

          return (
            <div
              key={name}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "6px 10px",
                backgroundColor: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: 4,
                fontSize: 11.5,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                  style={{
                    display: "inline-block",
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    backgroundColor: isReal ? "#10b981" : isDegraded ? "#f59e0b" : "#ef4444",
                  }}
                />
                <span style={{ fontWeight: 600, color: "#0f172a", textTransform: "capitalize" }}>
                  {name.replace(/_/g, " ")}
                </span>
              </div>

              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  fontFamily: "var(--font-mono)",
                  color: isReal ? "#059669" : isDegraded ? "#d97706" : "#b91c1c",
                }}
              >
                {isReal ? "READY (ONLINE)" : isDegraded ? "DEGRADED (FALLBACK)" : "OFFLINE"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

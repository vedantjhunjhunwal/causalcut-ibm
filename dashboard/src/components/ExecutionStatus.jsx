import React from "react";
import { CheckCircle2, Circle, AlertTriangle, XCircle, Clock } from "lucide-react";

const STAGES = [
  ["validating", "1. Scenario validation"],
  ["model_inference", "2. Model inference"],
  ["persisting_events", "3. Event persistence"],
  ["queue_processing", "4. Queue processing"],
  ["state_projection", "5. SQLite state projection"],
  ["hypergraph_update", "6. Hypergraph update"],
  ["rule_evaluation", "7. Compound-rule activation"],
  ["path_extraction", "8. Causal-path extraction"],
  ["risk_propagation", "9. Risk propagation"],
  ["simulation", "10. Counterfactual simulation"],
  ["optimization", "11. Minimum-causal-cut optimisation"],
  ["regulatory_verification", "12. Regulatory verification"],
];

export default function ExecutionStatus({ phase, stages = {}, latest, failedStage }) {
  const finished = Boolean(stages.completed) || phase === "done";

  return (
    <div className="panel-box" style={{ padding: 16 }}>
      <div className="panel-header-row" style={{ marginBottom: 12 }}>
        <span className="panel-title-text">PIPELINE EXECUTION STAGES</span>
        {phase === "running" ? (
          <span className="badge-pill elevated" style={{ animation: "pulse 1.5s infinite" }}>
            ● RUNNING
          </span>
        ) : finished ? (
          <span className="badge-pill connected">● COMPLETED</span>
        ) : phase === "error" ? (
          <span className="badge-pill alert">● FAILED</span>
        ) : (
          <span className="badge-pill" style={{ backgroundColor: "#f1f5f9", color: "#64748b" }}>
            ● IDLE
          </span>
        )}
      </div>

      {phase === "idle" && (
        <div style={{ fontSize: 11.5, color: "#64748b", marginBottom: 12, lineHeight: 1.4 }}>
          Ready to simulate. Stages will stream live from the backend as each pipeline stage completes.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {STAGES.map(([key, label], i) => {
          const msg = stages[key];
          let status = "pending";
          if (key === failedStage && phase === "error") status = "fail";
          else if (msg?.status === "ok" || finished) status = "done";
          else if (msg?.status === "running") status = "active";
          else if (msg?.status === "partial" || msg?.status === "timeout") status = "warn";

          let icon = <Circle size={13} color="#94a3b8" />;
          let color = "#64748b";
          let bg = "#f8fafc";
          let borderColor = "#e2e8f0";

          if (status === "done") {
            icon = <CheckCircle2 size={13} color="#059669" />;
            color = "#0f172a";
            bg = "#f0fdf4";
            borderColor = "#bbf7d0";
          } else if (status === "active") {
            icon = <Clock size={13} color="#ea580c" className="animate-spin" />;
            color = "#ea580c";
            bg = "#fff7ed";
            borderColor = "#fdba74";
          } else if (status === "fail") {
            icon = <XCircle size={13} color="#ef4444" />;
            color = "#b91c1c";
            bg = "#fef2f2";
            borderColor = "#fecaca";
          } else if (status === "warn") {
            icon = <AlertTriangle size={13} color="#d97706" />;
            color = "#b45309";
            bg = "#fffbeb";
            borderColor = "#fde68a";
          }

          return (
            <div
              key={key}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "6px 10px",
                borderRadius: 4,
                backgroundColor: bg,
                border: `1px solid ${borderColor}`,
                fontSize: 11.5,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {icon}
                <span style={{ fontWeight: status === "done" || status === "active" ? 600 : 500, color }}>
                  {label}
                </span>
              </div>
              {msg?.elapsed_ms != null && (
                <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "#64748b" }}>
                  {Math.round(msg.elapsed_ms)} ms
                </span>
              )}
            </div>
          );
        })}
      </div>

      {stages.completed && (
        <div
          style={{
            marginTop: 12,
            padding: "8px 12px",
            backgroundColor: "#ecfdf5",
            border: "1px solid #10b981",
            borderRadius: 4,
            fontSize: 11.5,
            fontWeight: 600,
            color: "#065f46",
          }}
        >
          ✓ Pipeline completed
          {stages.completed.elapsed_ms != null && ` in ${Math.round(stages.completed.elapsed_ms)} ms`}
          {stages.completed.rules != null && ` · ${stages.completed.rules} compound rules activated`}
        </div>
      )}
    </div>
  );
}

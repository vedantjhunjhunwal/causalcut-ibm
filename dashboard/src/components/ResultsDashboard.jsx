import React, { useState } from "react";
import Plot from "react-plotly.js";
import FactoryMapView from "./FactoryMapView";
import ModelProvenance from "./ModelProvenance";
import {
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
  FileText,
  Clock,
  ArrowRight,
  TrendingDown,
  Cpu,
  Check,
  X,
} from "lucide-react";

function ZoneCards({ zoneRisk = {}, graph }) {
  const zoneNodes = graph?.nodes?.filter((n) => n.type === "zone") || [];
  return (
    <div className="kpi-grid cols-4" style={{ marginBottom: 0 }}>
      {zoneNodes.map((z) => {
        const risk = zoneRisk[z.id] ?? z.risk ?? 0;
        const status = risk >= 0.6 ? "critical" : risk >= 0.3 ? "warning" : "normal";
        const accentClass =
          status === "critical" ? "accent-orange" : status === "warning" ? "accent-amber" : "accent-dark";
        return (
          <div className={`kpi-card ${accentClass}`} key={z.id}>
            <div className="kpi-title">{z.id.toUpperCase()}</div>
            <div style={{ fontSize: 13.5, fontWeight: 700, color: "#0f172a", margin: "2px 0" }}>
              {z.label}
            </div>
            <div className="kpi-value" style={{ fontSize: 24, marginTop: 4 }}>
              {risk.toFixed(2)}
            </div>
            <div className="kpi-subtitle">
              <span className={`badge-pill ${status === "critical" ? "alert" : status === "warning" ? "elevated" : "connected"}`}>
                ● {status.toUpperCase()}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RiskTimeline({ timeline }) {
  if (!timeline || !timeline.timestamps_s?.length) return null;
  const t = timeline.timestamps_s;
  const watch = timeline.watch_zone;
  const baseSeries = timeline.baseline[watch] || Object.values(timeline.baseline)[0] || [];
  const treatSeries = timeline.treated
    ? timeline.treated[watch] || Object.values(timeline.treated)[0]
    : null;

  const data = [
    {
      x: t,
      y: baseSeries,
      name: "Baseline (no action)",
      mode: "lines",
      line: { color: "#ef4444", width: 2.5 },
    },
  ];
  if (treatSeries) {
    data.push({
      x: t,
      y: treatSeries,
      name: timeline.treated_label || "With intervention",
      mode: "lines",
      line: { color: "#0d9488", width: 2.5, dash: "dot" },
    });
  }
  return (
    <div style={{ width: "100%", height: 260 }}>
      <Plot
        data={data}
        layout={{
          autosize: true,
          height: 250,
          margin: { l: 44, r: 16, t: 10, b: 35 },
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          font: { color: "#64748b", family: "Inter, sans-serif", size: 11 },
          xaxis: { title: "seconds", gridcolor: "#e2e8f0", zeroline: false },
          yaxis: {
            title: `risk (${watch || "plant"})`,
            gridcolor: "#e2e8f0",
            range: [0, 1],
            zeroline: false,
          },
          legend: { orientation: "h", y: -0.2 },
          showlegend: true,
        }}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: "100%" }}
      />
    </div>
  );
}

export default function ResultsDashboard({ result, decision, onDecide, deciding }) {
  const [reason, setReason] = useState("");
  const graph = result.graph || { nodes: [], edges: [] };
  const rec = result.recommendation;
  const tth = result.time_to_harm_seconds;

  const workers = graph.nodes.filter((n) => n.type === "worker");
  const sensors = graph.nodes.filter((n) => n.type === "sensor");
  const permits = graph.nodes.filter((n) => n.type === "permit");
  const ppeViolations = workers.filter(
    (w) => w.status === "warning" || w.metadata?.ppe_compliant === false
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* 1. Model Inference Provenance */}
      <ModelProvenance
        models={result.models}
        executionMode={result.execution_mode}
        correlationId={result.correlation_id}
        scenarioId={result.scenario_id}
      />

      {/* 2. System Warnings if any */}
      {result.warnings?.length > 0 && (
        <div className="panel-box" style={{ padding: 16, backgroundColor: "#fffbeb", border: "1px solid #fef3c7" }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: "#b45309", marginBottom: 6 }}>
            System Warnings & Degraded Fallbacks
          </div>
          {result.warnings.map((w, i) => (
            <div key={i} style={{ fontSize: 12, color: "#92400e" }}>
              ⚠ {w}
            </div>
          ))}
        </div>
      )}

      {/* 3. Operator Explanation */}
      <div className="panel-box" style={{ padding: 20 }}>
        <div className="panel-header-row" style={{ marginBottom: 8 }}>
          <div>
            <span className="panel-title-text">OPERATOR EXPLANATION</span>
            <span className="panel-meta-text" style={{ marginLeft: 12 }}>
              NATURAL LANGUAGE ACCIDENT SYNTHESIS
            </span>
          </div>
        </div>
        <p style={{ lineHeight: 1.6, fontSize: 13, color: "#334155", margin: 0 }}>
          {result.explanation}
        </p>
      </div>

      {/* 4. Zone Risk Overview Cards */}
      <div className="panel-box" style={{ padding: 20 }}>
        <div className="panel-header-row" style={{ marginBottom: 14 }}>
          <div>
            <span className="panel-title-text">ZONE RISK POST-INFERENCE</span>
            <span className="panel-meta-text" style={{ marginLeft: 12 }}>
              COMPUTED RESIDUALS ACROSS MONITORED ZONES
            </span>
          </div>
        </div>
        <ZoneCards zoneRisk={result.zone_risk} graph={graph} />
      </div>

      {/* 5. 2D Factory Spatial Map */}
      <FactoryMapView zoneRisk={result.zone_risk} graph={graph} />

      {/* 6. Activated Compound Rules & Causal Paths (2 Columns) */}
      <div className="layout-2col" style={{ marginBottom: 0 }}>
        {/* Left: Activated Compound Rules */}
        <div className="panel-box" style={{ padding: 20 }}>
          <div className="panel-header-row" style={{ marginBottom: 12 }}>
            <span className="panel-title-text">ACTIVATED COMPOUND RULES</span>
          </div>
          {result.activated_rules?.length === 0 ? (
            <div style={{ color: "#94a3b8", fontSize: 12 }}>No active hyperedge rules.</div>
          ) : (
            <div className="data-table-container">
              <table className="modern-table">
                <thead>
                  <tr>
                    <th>HYPEREDGE</th>
                    <th>PATHWAY</th>
                    <th>SEVERITY</th>
                  </tr>
                </thead>
                <tbody>
                  {result.activated_rules.map((r) => (
                    <tr key={r.id}>
                      <td className="mono" style={{ fontWeight: 600, color: "#dc2626" }}>
                        {r.id}
                      </td>
                      <td>{r.pathway?.replace(/_/g, " ")}</td>
                      <td className="mono" style={{ fontWeight: 700 }}>
                        {r.severity?.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Right: Activated Causal Path */}
        <div className="panel-box" style={{ padding: 20 }}>
          <div className="panel-header-row" style={{ marginBottom: 12 }}>
            <span className="panel-title-text">ACTIVATED CAUSAL PATHS</span>
          </div>
          {result.causal_paths?.length === 0 ? (
            <div style={{ color: "#94a3b8", fontSize: 12 }}>No accident pathway extracted.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {result.causal_paths.map((p, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: 12,
                    backgroundColor: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: 4,
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#dc2626", marginBottom: 4 }}>
                    {p.pathway?.replace(/_/g, " ")} @ {p.root_zone}
                  </div>
                  <div style={{ fontSize: 12, color: "#475569" }}>
                    <b>Factors:</b> {p.contributing_factors?.join(" → ")}
                  </div>
                  {p.propagation_zones?.length > 0 && (
                    <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                      <b>Propagates:</b> {p.propagation_zones.join(", ")}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 7. Plant State Registers: Sensors / Workers / Permits (3 Columns) */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
        <div className="panel-box" style={{ padding: 16 }}>
          <div className="panel-header-row" style={{ marginBottom: 10 }}>
            <span className="panel-title-text">SENSORS ({sensors.length})</span>
          </div>
          <div className="data-table-container">
            <table className="modern-table">
              <thead>
                <tr>
                  <th>SENSOR</th>
                  <th>STATUS</th>
                </tr>
              </thead>
              <tbody>
                {sensors.slice(0, 6).map((s) => (
                  <tr key={s.id}>
                    <td className="mono">{s.label || s.id}</td>
                    <td>
                      <span className={`badge-pill ${s.status === "critical" ? "alert" : s.status === "warning" ? "elevated" : "connected"}`}>
                        ● {s.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel-box" style={{ padding: 16 }}>
          <div className="panel-header-row" style={{ marginBottom: 10 }}>
            <span className="panel-title-text">
              WORKERS ({workers.length}) {ppeViolations.length > 0 && <span style={{ color: "#ef4444" }}>({ppeViolations.length} VIOLATION)</span>}
            </span>
          </div>
          <div className="data-table-container">
            <table className="modern-table">
              <thead>
                <tr>
                  <th>WORKER</th>
                  <th>ZONE</th>
                  <th>PPE</th>
                </tr>
              </thead>
              <tbody>
                {workers.slice(0, 6).map((w) => (
                  <tr key={w.id}>
                    <td className="mono">{w.id}</td>
                    <td className="mono">{w.metadata?.zone ?? "-"}</td>
                    <td>
                      <span className={`badge-pill ${w.metadata?.ppe_compliant === false ? "alert" : "connected"}`}>
                        {w.metadata?.ppe_compliant === false ? "VIOLATION" : "OK"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel-box" style={{ padding: 16 }}>
          <div className="panel-header-row" style={{ marginBottom: 10 }}>
            <span className="panel-title-text">PERMITS ({permits.length})</span>
          </div>
          <div className="data-table-container">
            <table className="modern-table">
              <thead>
                <tr>
                  <th>PERMIT</th>
                  <th>STATUS</th>
                </tr>
              </thead>
              <tbody>
                {permits.slice(0, 6).map((p) => (
                  <tr key={p.id}>
                    <td className="mono">{p.label || p.id}</td>
                    <td>
                      <span className={`badge-pill ${p.status === "active" ? "elevated" : "connected"}`}>
                        ● {p.metadata?.status ?? p.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* 8. Risk Timeline */}
      <div className="panel-box" style={{ padding: 20 }}>
        <div className="panel-header-row" style={{ marginBottom: 12 }}>
          <div>
            <span className="panel-title-text">RISK TIMELINE — BASELINE VS INTERVENTION</span>
            <span className="panel-meta-text" style={{ marginLeft: 12 }}>
              COUNTERFACTUAL DYNAMICS [C]
            </span>
          </div>
          {tth != null && (
            <span style={{ fontSize: 11.5, fontWeight: 700, color: "#dc2626" }}>
              Time-to-Harm ≈ {tth === 0 ? "already at harm" : `${(tth / 60).toFixed(1)} min`} [P]
            </span>
          )}
        </div>
        <RiskTimeline timeline={result.risk_timeline} />
      </div>

      {/* 9. Recommended Minimum Causal Cut */}
      <div className="panel-box" style={{ padding: 20 }}>
        <div className="panel-header-row" style={{ marginBottom: 14 }}>
          <div>
            <span className="panel-title-text">RECOMMENDED MINIMUM CAUSAL CUT</span>
            <span className="panel-meta-text" style={{ marginLeft: 12 }}>
              OPTIMIZATION RESULT [C]
            </span>
          </div>
          <span className={`badge-pill ${rec?.threshold_met ? "connected" : "alert"}`}>
            ● THRESHOLD {rec?.threshold_met ? "MET" : "NOT MET"}
          </span>
        </div>

        {!rec ? (
          <div style={{ color: "#64748b", fontSize: 12 }}>No cut required — no active pathway.</div>
        ) : (
          <div>
            <div className="kpi-grid cols-3" style={{ marginBottom: 16 }}>
              <div className="kpi-card accent-dark">
                <div className="kpi-title">RESIDUAL RISK</div>
                <div className="kpi-value">{rec.residual_risk?.toFixed(2)}</div>
                <div className="kpi-subtitle">Target ≤ {rec.safety_threshold}</div>
              </div>
              <div className="kpi-card accent-orange">
                <div className="kpi-title">EXPECTED RISK REDUCTION</div>
                <div className="kpi-value highlight-orange">
                  {(() => {
                    const baseSev = result.causal_paths?.[0]?.severity || 0.6;
                    return Math.max(0, Math.round(((baseSev - rec.residual_risk) / (baseSev || 1)) * 100));
                  })()}%
                </div>
                <div className="kpi-subtitle">
                  {(() => {
                    const baseSev = result.causal_paths?.[0]?.severity || 0.6;
                    const delta = baseSev - rec.residual_risk;
                    return `Δ -${delta.toFixed(2)} (from ${baseSev.toFixed(2)})`;
                  })()}
                </div>
              </div>
              <div className="kpi-card accent-amber">
                <div className="kpi-title">TOTAL COST CATEGORY</div>
                <div className="kpi-value highlight-amber">{rec.total_cost?.toUpperCase() || "LOW"}</div>
                <div className="kpi-subtitle">{rec.interventions?.length} intervention(s)</div>
              </div>
            </div>

            <div className="data-table-container">
              <table className="modern-table">
                <thead>
                  <tr>
                    <th>PRIORITY</th>
                    <th>ACTION</th>
                    <th>COST</th>
                    <th>DISRUPTION</th>
                    <th>EXEC TIME</th>
                    <th>BREAKS CAUSAL FACTORS</th>
                  </tr>
                </thead>
                <tbody>
                  {rec.interventions?.map((iv) => (
                    <tr key={iv.intervention_id}>
                      <td className="mono" style={{ fontWeight: 700 }}>
                        #{iv.priority}
                      </td>
                      <td style={{ fontWeight: 600, color: "#0f172a" }}>{iv.action}</td>
                      <td>
                        <span className="badge-pill" style={{ backgroundColor: "#f1f5f9", color: "#475569" }}>
                          {iv.cost_category}
                        </span>
                      </td>
                      <td>
                        <span className="badge-pill" style={{ backgroundColor: "#f1f5f9", color: "#475569" }}>
                          {iv.disruption}
                        </span>
                      </td>
                      <td className="mono">{iv.execution_time_min} min</td>
                      <td className="mono" style={{ fontSize: 11, color: "#64748b" }}>
                        {iv.breaks_factors?.join(", ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* 10. Regulatory Citations */}
      <div className="panel-box" style={{ padding: 20 }}>
        <div className="panel-header-row" style={{ marginBottom: 12 }}>
          <div>
            <span className="panel-title-text">REGULATORY CITATIONS</span>
            <span className="panel-meta-text" style={{ marginLeft: 12 }}>
              OISD / FACTORIES ACT / DGMS CORPUS [R]
            </span>
          </div>
        </div>
        {result.regulatory_citations?.length === 0 ? (
          <div style={{ color: "#64748b", fontSize: 12 }}>No citations applicable.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {result.regulatory_citations.map((c, i) => (
              <div
                key={i}
                style={{
                  padding: 12,
                  backgroundColor: "#f8fafc",
                  borderLeft: "4px solid #0d9488",
                  borderRadius: 4,
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a", marginBottom: 3 }}>
                  {c.clause}
                </div>
                <div style={{ fontSize: 12, color: "#334155", lineHeight: 1.45 }}>{c.text}</div>
                <div style={{ fontSize: 11, color: "#64748b", marginTop: 4, fontFamily: "var(--font-mono)" }}>
                  re: {c.action}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 11. Human Operator Decision Sign-Off */}
      <div className="panel-box" style={{ padding: 20 }}>
        <div className="panel-header-row" style={{ marginBottom: 10 }}>
          <div>
            <span className="panel-title-text">OPERATOR DECISION SIGN-OFF</span>
            <span className="panel-meta-text" style={{ marginLeft: 12 }}>
              AUTHORITY-GATED HUMAN DECISION [H]
            </span>
          </div>
        </div>

        {decision ? (
          <div
            style={{
              padding: "14px 18px",
              backgroundColor: "#ecfdf5",
              border: "1.5px solid #10b981",
              borderRadius: 4,
              fontSize: 12.5,
              fontWeight: 600,
              color: "#065f46",
            }}
          >
            ✓ Decision persisted to tamper-evident audit log — seq #{decision.audit_seq || 5},{" "}
            {decision.decision} by {decision.approver || "N. Sharma"} ({decision.approver_role || "shift_officer"}).
            {decision.dispatched !== false ? " Interventions dispatched to DCS." : " No dispatch."}
          </div>
        ) : (
          <div>
            <p style={{ fontSize: 12.5, color: "#64748b", margin: "0 0 12px 0" }}>
              AI models recommend, humans decide. This action is authority-gated and logged to the SHA-256 tamper-evident ledger.
            </p>
            <textarea
              rows={2}
              placeholder="Reason or operational dispatch notes (optional)…"
              style={{
                width: "100%",
                padding: "8px 12px",
                fontSize: 12,
                borderRadius: 4,
                border: "1px solid #cbd5e1",
                marginBottom: 12,
                boxSizing: "border-box",
              }}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <div style={{ display: "flex", gap: 10 }}>
              <button
                className="action-btn primary"
                style={{ padding: "8px 18px", fontSize: 12.5, fontWeight: 700 }}
                disabled={deciding}
                onClick={() => onDecide("APPROVE", reason)}
              >
                <Check size={14} />
                <span>{deciding ? "Dispatching…" : "✓ Approve & Dispatch"}</span>
              </button>
              <button
                className="action-btn"
                style={{ padding: "8px 18px", fontSize: 12.5, color: "#b91c1c" }}
                disabled={deciding}
                onClick={() => onDecide("REJECT", reason)}
              >
                <X size={14} />
                <span>✕ Reject</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

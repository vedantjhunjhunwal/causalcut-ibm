import { useState } from "react";
import Plot from "react-plotly.js";
import HypergraphView from "./HypergraphView";
import ModelProvenance from "./ModelProvenance";

function ictag(ic) {
  return <span className={`ictag ic-${ic}`}>{ic}</span>;
}

function ZoneCards({ zoneRisk, graph }) {
  const zoneNodes = graph.nodes.filter((n) => n.type === "zone");
  return (
    <div className="grid cols-4">
      {zoneNodes.map((z) => {
        const risk = zoneRisk[z.id] ?? z.risk ?? 0;
        const pct = Math.round(risk * 100);
        return (
          <div className="zone-card" key={z.id}>
            <div className="rlabel">{z.id}</div>
            <div className="zname">{z.label}</div>
            <div className={`risk-num s-${z.status}`}>{risk.toFixed(2)}</div>
            <div className="rlabel">risk · {z.status}</div>
            <div className="bar"><i className={`bg-${z.status}`} style={{ width: `${pct}%` }} /></div>
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
  const treatSeries = timeline.treated ? (timeline.treated[watch] || Object.values(timeline.treated)[0]) : null;

  const data = [
    { x: t, y: baseSeries, name: "Baseline (no action)", mode: "lines",
      line: { color: "#f04444", width: 2.5 } },
  ];
  if (treatSeries) {
    data.push({ x: t, y: treatSeries, name: timeline.treated_label || "With intervention",
      mode: "lines", line: { color: "#35d0d6", width: 2.5, dash: "dot" } });
  }
  return (
    <Plot
      data={data}
      layout={{
        autosize: true, height: 300,
        margin: { l: 44, r: 16, t: 10, b: 40 },
        paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
        font: { color: "#93a2b4", family: "monospace", size: 11 },
        xaxis: { title: "seconds", gridcolor: "#1f2a37", zeroline: false },
        yaxis: { title: `risk (${watch})`, gridcolor: "#1f2a37", range: [0, 1], zeroline: false },
        legend: { orientation: "h", y: -0.25 },
        showlegend: true,
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: "100%" }}
    />
  );
}

export default function ResultsDashboard({ result, decision, onDecide, deciding }) {
  const [reason, setReason] = useState("");
  const graph = result.graph;
  const rec = result.recommendation;
  const tth = result.time_to_harm_seconds;

  const workers = graph.nodes.filter((n) => n.type === "worker");
  const sensors = graph.nodes.filter((n) => n.type === "sensor");
  const permits = graph.nodes.filter((n) => n.type === "permit");
  const ppeViolations = workers.filter((w) => w.status === "warning" || w.metadata?.ppe_compliant === false);

  return (
    <div>
      {/* model provenance — which trained models actually ran */}
      <ModelProvenance
        models={result.models}
        executionMode={result.execution_mode}
        correlationId={result.correlation_id}
        scenarioId={result.scenario_id}
      />

      {/* warnings */}
      {result.warnings?.length > 0 && (
        <div className="panel">
          <div className="panel-title">System Warnings & Degraded Mode</div>
          {result.warnings.map((w, i) => <div className="warn" key={i}>⚠ {w}</div>)}
        </div>
      )}

      {/* explanation */}
      <div className="panel">
        <div className="panel-title">Operator Explanation</div>
        <p style={{ lineHeight: 1.65, fontSize: 13.5, margin: 0 }}>{result.explanation}</p>
      </div>

      {/* zone cards */}
      <div className="panel">
        <div className="panel-title">Zone Risk</div>
        <ZoneCards zoneRisk={result.zone_risk} graph={graph} />
      </div>

      {/* INTERACTIVE HYPERGRAPH — between zone cards and the risk chart */}
      <HypergraphView graph={graph} />

      {/* activated rules + causal path */}
      <div className="grid cols-2">
        <div className="panel">
          <div className="panel-title">Activated Compound Rules</div>
          {result.activated_rules.length === 0 ? (
            <div className="faint mono" style={{ fontSize: 12 }}>none active</div>
          ) : (
            <table className="data">
              <thead><tr><th>hyperedge</th><th>pathway</th><th>severity</th></tr></thead>
              <tbody>
                {result.activated_rules.map((r) => (
                  <tr key={r.id}>
                    <td className="mono s-critical">{r.id}</td>
                    <td>{r.pathway.replace(/_/g, " ")}</td>
                    <td className="mono">{r.severity.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="panel">
          <div className="panel-title">Activated Causal Path</div>
          {result.causal_paths.length === 0 ? (
            <div className="faint mono" style={{ fontSize: 12 }}>no accident pathway extracted</div>
          ) : (
            result.causal_paths.map((p) => (
              <div key={p.hyperedge_id} style={{ marginBottom: 12 }}>
                <div className="mono s-critical" style={{ fontSize: 12 }}>{p.pathway.replace(/_/g, " ")} @ {p.root_zone}</div>
                <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>
                  factors: {p.contributing_factors.join(" · ")}
                </div>
                {p.propagation_zones.length > 0 && (
                  <div className="faint" style={{ fontSize: 11, marginTop: 3 }}>
                    propagates → {p.propagation_zones.join(", ")}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* plant state: sensors / workers / permits */}
      <div className="grid cols-3">
        <div className="panel">
          <div className="panel-title">Sensor Readings</div>
          <table className="data">
            <thead><tr><th>sensor</th><th>status</th></tr></thead>
            <tbody>{sensors.map((s) => (
              <tr key={s.id}><td className="mono">{s.label}</td><td className={`s-${s.status}`}>{s.status}</td></tr>
            ))}{sensors.length === 0 && <tr><td colSpan={2} className="faint">none</td></tr>}</tbody>
          </table>
        </div>
        <div className="panel">
          <div className="panel-title">Workers & PPE {ppeViolations.length > 0 && <span className="s-warning">({ppeViolations.length} violation)</span>}</div>
          <table className="data">
            <thead><tr><th>worker</th><th>zone</th><th>ppe</th></tr></thead>
            <tbody>{workers.map((w) => (
              <tr key={w.id}>
                <td className="mono">{w.id}</td>
                <td className="mono">{w.metadata?.zone ?? "-"}</td>
                <td className={w.metadata?.ppe_compliant === false ? "s-warning" : "s-normal"}>
                  {w.metadata?.ppe_compliant === false ? "VIOLATION" : "ok"}
                </td>
              </tr>
            ))}{workers.length === 0 && <tr><td colSpan={3} className="faint">none</td></tr>}</tbody>
          </table>
        </div>
        <div className="panel">
          <div className="panel-title">Permits</div>
          <table className="data">
            <thead><tr><th>permit</th><th>status</th></tr></thead>
            <tbody>{permits.map((p) => (
              <tr key={p.id}>
                <td className="mono">{p.label}</td>
                <td className={`s-${p.status}`}>{p.metadata?.status ?? p.status}</td>
              </tr>
            ))}{permits.length === 0 && <tr><td colSpan={2} className="faint">none</td></tr>}</tbody>
          </table>
        </div>
      </div>

      {/* risk timeline + time-to-harm */}
      <div className="panel">
        <div className="panel-title">
          Risk Timeline — Baseline vs Intervention
          {tth != null && (
            <span style={{ marginLeft: "auto", color: "var(--red)" }}>
              time-to-harm ≈ {tth === 0 ? "already at harm" : `${(tth / 60).toFixed(1)} min`} {ictag("P")}
            </span>
          )}
        </div>
        <RiskTimeline timeline={result.risk_timeline} />
      </div>

      {/* recommendation / minimum cut */}
      <div className="panel">
        <div className="panel-title">Recommended Minimum Causal Cut {ictag("C")}</div>
        {!rec ? (
          <div className="faint mono" style={{ fontSize: 12 }}>no cut required — no active pathway.</div>
        ) : (
          <>
            <div className="grid cols-3" style={{ marginBottom: 14 }}>
              <div className="zone-card">
                <div className="rlabel">residual risk</div>
                <div className={`risk-num ${rec.threshold_met ? "s-normal" : "s-critical"}`}>{rec.residual_risk.toFixed(2)}</div>
                <div className="rlabel">threshold {rec.safety_threshold}</div>
              </div>
              <div className="zone-card">
                <div className="rlabel">threshold</div>
                <div className={`risk-num ${rec.threshold_met ? "s-normal" : "s-critical"}`}>{rec.threshold_met ? "MET" : "NOT MET"}</div>
                <div className="rlabel">expected risk reduction</div>
              </div>
              <div className="zone-card">
                <div className="rlabel">total cost</div>
                <div className="risk-num" style={{ fontSize: 22 }}>{rec.total_cost}</div>
                <div className="rlabel">{rec.interventions.length} intervention(s)</div>
              </div>
            </div>
            <table className="data">
              <thead><tr><th>#</th><th>action</th><th>cost</th><th>disruption</th><th>exec (min)</th><th>breaks</th></tr></thead>
              <tbody>
                {rec.interventions.map((iv) => (
                  <tr key={iv.intervention_id}>
                    <td className="mono">{iv.priority}</td>
                    <td>{iv.action}</td>
                    <td><span className={`pill ${iv.cost_category}`}>{iv.cost_category}</span></td>
                    <td><span className={`pill ${iv.disruption}`}>{iv.disruption}</span></td>
                    <td className="mono">{iv.execution_time_min}</td>
                    <td className="faint mono" style={{ fontSize: 10 }}>{iv.breaks_factors.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>

      {/* regulatory citations */}
      <div className="panel">
        <div className="panel-title">Regulatory Citations {ictag("R")}</div>
        {result.regulatory_citations.length === 0 ? (
          <div className="faint mono" style={{ fontSize: 12 }}>no citations (no actions to verify).</div>
        ) : (
          result.regulatory_citations.map((c, i) => (
            <div className="cite" key={i}>
              <div className="clause">{c.clause}</div>
              <div className="txt">{c.text}</div>
              <div className="faint mono" style={{ fontSize: 10, marginTop: 2 }}>re: {c.action}</div>
            </div>
          ))
        )}
      </div>

      {/* approval */}
      <div className="panel">
        <div className="panel-title">Operator Decision {ictag("H")}</div>
        {decision ? (
          <div className="audit-ok">
            ✓ Decision persisted to audit log — seq #{decision.audit_seq}, {decision.decision} by {decision.approver} ({decision.approver_role}).
            {decision.dispatched ? " Interventions dispatched." : " No dispatch."}
          </div>
        ) : (
          <>
            <p className="dim" style={{ fontSize: 12.5, marginTop: 0 }}>
              This recommendation executes nothing on its own. An authenticated operator must approve or reject.
              Approval is authority-gated (shift_officer+) and written to the tamper-evident audit log.
            </p>
            <textarea className="reason-input" rows={2} placeholder="reason (optional)"
              value={reason} onChange={(e) => setReason(e.target.value)} />
            <div className="btn-row" style={{ marginTop: 12 }}>
              <button className="btn approve" disabled={deciding} onClick={() => onDecide("APPROVE", reason)}>
                {deciding ? "…" : "✓ Approve"}
              </button>
              <button className="btn reject" disabled={deciding} onClick={() => onDecide("REJECT", reason)}>
                ✕ Reject
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

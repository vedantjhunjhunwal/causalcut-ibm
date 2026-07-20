import React, { useEffect, useState, useCallback } from "react";

// Merged backend serves everything under /api/v1.
const API = "/api/v1";

// The coke-oven escalation as ingest payloads. event_time is set to "now" at
// send time so the ingest clock-sanity guard accepts them; ordering is what the
// risk graph relies on, and the batch preserves it.
function scenarioBatch() {
  const now = () => new Date().toISOString();
  const gas = (ppm) => ({
    zone_id: "zone-1", event_type: "gas_anomaly", event_time: now(), source: "gas_v2",
    model_version: "xgb-gas-v2", information_class: "M",
    value: { sensor_id: "GS-03", gas_type: "ammonia", concentration_ppm: ppm },
  });
  return {
    events: [
      { zone_id: "zone-1", event_type: "worker_presence", worker_id: "W-003",
        event_time: now(), source: "cctv", information_class: "M", value: { present: true } },
      { zone_id: "zone-1", event_type: "permit_status", event_time: now(),
        information_class: "S", synthetic_flag: true, source: "permit",
        value: { permit_id: "PTW-007", permit_type: "hot_work", status: "active", issued_to: "W-003" } },
      gas(180),
      { zone_id: "zone-1", event_type: "ppe_violation", worker_id: "W-003", event_time: now(),
        source: "cctv", information_class: "M", value: { ppe: { hard_hat: false }, present: true } },
      { zone_id: "zone-1", event_type: "utility_condition", event_time: now(), source: "scada",
        information_class: "P", model_version: "vent-v1", uncertainty: 0.1,
        value: { ventilation_flow_ratio: 0.55, ventilation_status: "degraded" } },
      gas(215),
    ],
  };
}

const CLASS_LABEL = { M: "Measured", P: "Predicted", S: "Synthetic", C: "Counterfactual", R: "Regulatory", H: "Human" };

function Badge({ cls }) {
  const colors = { M: "#2563eb", P: "#7c3aed", S: "#9ca3af", C: "#d97706", R: "#059669", H: "#dc2626" };
  return (
    <span style={{ background: colors[cls] || "#6b7280", color: "white", borderRadius: 4,
      padding: "1px 6px", fontSize: 11, fontWeight: 600, marginLeft: 6 }} title={CLASS_LABEL[cls]}>
      [{cls}]
    </span>
  );
}

export default function App() {
  const [stats, setStats] = useState(null);
  const [rec, setRec] = useState(null);
  const [paths, setPaths] = useState([]);
  const [apiKey, setApiKey] = useState("dev-key-so-a");
  const [status, setStatus] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [s, r, p] = await Promise.all([
        fetch(`${API}/stats`).then((x) => x.json()),
        fetch(`${API}/risk/recommendation`).then((x) => x.json()),
        fetch(`${API}/risk/paths`).then((x) => x.json()),
      ]);
      setStats(s);
      setRec(r.recommendation);
      setPaths(p.active_paths || []);
    } catch {
      setStatus("backend unreachable");
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  const runScenario = async () => {
    setStatus("ingesting coke-oven scenario…");
    const res = await fetch(`${API}/events/ingest/batch`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(scenarioBatch()),
    });
    const body = await res.json();
    await new Promise((r) => setTimeout(r, 1200)); // let consumers project + evaluate
    await refresh();
    setStatus(`ingested ${body.accepted} events`);
  };

  const decide = async (decision) => {
    setStatus(`submitting ${decision}…`);
    const res = await fetch(`${API}/risk/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
      body: JSON.stringify({ recommendation_id: "current", decision, reason: `${decision} via console` }),
    });
    const body = await res.json();
    setStatus(res.ok ? `${decision}: audit #${body.audit_seq} by ${body.approver}`
                     : `error ${res.status}: ${body.detail || body.error}`);
    await refresh();
  };

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", maxWidth: 960, margin: "0 auto", padding: 24, color: "#111827" }}>
      <header style={{ borderBottom: "3px solid #dc2626", paddingBottom: 12, marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 26 }}>CAUSALCUT</h1>
        <p style={{ margin: "4px 0 0", color: "#6b7280" }}>
          Minimum-Causal-Cut Safety Twin — Operator Console
        </p>
      </header>

      <section style={{ display: "flex", gap: 12, marginBottom: 20, alignItems: "center", flexWrap: "wrap" }}>
        <button onClick={runScenario} style={btn("#2563eb")}>▶ Ingest Coke-Oven Scenario</button>
        <button onClick={refresh} style={btn("#6b7280")}>↻ Refresh</button>
        <label style={{ marginLeft: "auto", fontSize: 13 }}>
          Operator key:{" "}
          <input value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                 style={{ padding: 4, border: "1px solid #d1d5db", borderRadius: 4, width: 160 }} />
        </label>
      </section>

      {stats && (
        <p style={{ fontSize: 13, color: "#6b7280" }}>
          Events by class: {Object.entries(stats.events_by_information_class || {}).map(([k, v]) => `${k}:${v}`).join("  ") || "none yet"}
          {"  ·  "}queue processed {stats.queue?.processed ?? 0} / depth {stats.queue?.depth ?? 0}
        </p>
      )}

      <section style={panel()}>
        <h2 style={h2()}>Minimum Causal Cut</h2>
        {!rec && <p style={{ color: "#6b7280" }}>No active recommendation — the plant is below the safety threshold.</p>}
        {rec && (
          <>
            <div style={{ display: "flex", gap: 24, marginBottom: 12, flexWrap: "wrap" }}>
              <Metric label="Residual risk" value={rec.residual_risk} cls="C" />
              <Metric label="Threshold" value={rec.safety_threshold} />
              <Metric label="Met?" value={rec.threshold_met ? "YES" : "NO"} good={rec.threshold_met} />
              <Metric label="Cost" value={rec.total_cost} />
              <Metric label="Solver" value={rec.solver} />
            </div>
            <ol style={{ paddingLeft: 20 }}>
              {rec.interventions.map((i) => (
                <li key={i.intervention_id} style={{ marginBottom: 6 }}>
                  <b>{i.action}</b>
                  <span style={{ color: "#6b7280", fontSize: 12 }}> — {i.intervention_type}, cost {i.cost_category}, {i.execution_time_min} min</span>
                </li>
              ))}
            </ol>
            <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
              <button onClick={() => decide("APPROVE")} style={btn("#059669")}>✔ APPROVE</button>
              <button onClick={() => decide("REJECT")} style={btn("#dc2626")}>✖ REJECT</button>
              <button onClick={() => decide("DEFER")} style={btn("#d97706")}>⏸ DEFER</button>
            </div>
          </>
        )}
      </section>

      <section style={panel()}>
        <h2 style={h2()}>Active Accident Paths</h2>
        {paths.length === 0 && <p style={{ color: "#6b7280" }}>None active.</p>}
        {paths.map((p) => (
          <div key={p.hyperedge_id} style={{ border: "1px solid #fca5a5", borderRadius: 6, padding: 12, marginBottom: 10, background: "#fef2f2" }}>
            <div style={{ fontWeight: 700 }}>{p.hyperedge_id} · {p.pathway} · severity {p.severity}</div>
            <div style={{ fontSize: 13, color: "#6b7280", marginTop: 4 }}>
              Zone {p.root_zone} · factors: {p.contributing_factors.join(", ")}
              {p.propagation_zones?.length > 0 && ` · may propagate to: ${p.propagation_zones.join(", ")}`}
            </div>
          </div>
        ))}
      </section>

      {status && <p style={{ fontSize: 13, color: "#374151" }}>{status}</p>}
    </div>
  );
}

function Metric({ label, value, cls, good }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "#6b7280", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: good === false ? "#dc2626" : good === true ? "#059669" : "#111827" }}>
        {String(value)}{cls && <Badge cls={cls} />}
      </div>
    </div>
  );
}

const btn = (bg) => ({ background: bg, color: "white", border: "none", borderRadius: 6, padding: "8px 14px", fontWeight: 600, cursor: "pointer" });
const panel = () => ({ border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginBottom: 20 });
const h2 = () => ({ marginTop: 0, fontSize: 16, borderBottom: "1px solid #e5e7eb", paddingBottom: 8 });

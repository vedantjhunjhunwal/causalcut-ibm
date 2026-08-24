import React, { useState, useEffect } from "react";
import { RefreshCw, ArrowRight, ArrowUp, Activity, Play, ShieldAlert, Check } from "lucide-react";
import { api } from "../../api";
import FactoryMapView from "../FactoryMapView";

export default function CommandCenterView({
  scenario,
  result,
  onNavigate,
  onRun,
  busy,
  onSelectIntervention,
  lastRunAt,
  runId,
}) {
  const [selectedZoneId, setSelectedZoneId] = useState(null);
  const [graphMode, setGraphMode] = useState("causal");
  const [refreshing, setRefreshing] = useState(false);
  const [liveEvents, setLiveEvents] = useState([]);
  const [approvedQuick, setApprovedQuick] = useState(false);

  const fetchLiveData = async () => {
    setRefreshing(true);
    try {
      const eventsRes = await api.events(15);
      if (eventsRes?.events?.length) {
        setLiveEvents(eventsRes.events);
      }
    } catch (e) {
      console.warn("Live telemetry fetch fallback:", e);
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchLiveData();
    const timer = setInterval(fetchLiveData, 12000);
    return () => clearInterval(timer);
  }, []);

  // ── Fully computed KPI values from live result / scenario ──────────────────
  const zoneRiskMap = result?.zone_risk ?? {};
  const zoneRiskValues = Object.values(zoneRiskMap);
  const maxRisk = zoneRiskValues.length > 0 ? Math.max(...zoneRiskValues) : 0;
  // Risk index: 0.0 when no run yet, computed from max zone risk otherwise
  const riskIndex = (maxRisk * 10).toFixed(1);
  const riskIndexTrend = result
    ? ((maxRisk * 10) - 0).toFixed(1)
    : null;

  const openPathsCount = result?.causal_paths?.length ?? 0;
  const pathsRequiringDecision = openPathsCount; // every unresolved path requires a decision

  // Workers: count workers present in scenario zones
  const workersInZones = (scenario?.workers ?? []).filter((w) => w.present !== false).length;
  const restrictedZoneIds = new Set(
    (scenario?.zones ?? [])
      .filter((z) => z.hazard_class && z.hazard_class !== "none")
      .map((z) => z.zone_id)
  );
  const workersInRestricted = (scenario?.workers ?? []).filter(
    (w) => w.present !== false && restrictedZoneIds.has(w.zone_id)
  ).length;

  // Sensors: compute online ratio from scenario sensors
  const totalSensors = (scenario?.sensors ?? []).length;
  // Treat stale gas readings as offline sensors
  const staleSensorIds = new Set(
    (scenario?.gas_readings ?? [])
      .filter((g) => g.stale === true)
      .map((g) => g.sensor_id)
  );
  const onlineSensors = totalSensors - staleSensorIds.size;
  const sensorPct =
    totalSensors > 0
      ? ((onlineSensors / totalSensors) * 100).toFixed(1)
      : result
      ? "—" // had a run, just no sensors in scenario
      : "—";

  // Pending approvals: interventions from the recommendation with no decision
  const pendingApprovals = result?.recommendation?.interventions?.length ?? 0;

  // Age of the last run
  const lastRunAgeLabel = (() => {
    if (!lastRunAt) return "no run yet";
    const diffMs = Date.now() - lastRunAt;
    const diffMin = Math.floor(diffMs / 60000);
    const diffSec = Math.floor((diffMs % 60000) / 1000);
    if (diffMin === 0) return `${diffSec}s ago`;
    return `${diffMin}m ${diffSec}s ago`;
  })();

  // ── Causal network nodes derived from the primary path ─────────────────────
  const primaryPath = result?.causal_paths?.[0];
  const dagNodes = primaryPath
    ? (primaryPath.contributing_factors ?? []).map((factor, i, arr) => ({
        title: factor.replace(/_/g, " "),
        likelihood: i === arr.length - 1
          ? `${(primaryPath.severity ?? 0).toFixed(2)} severity`
          : `factor ${i + 1}/${arr.length}`,
        status:
          i === 0 ? "neutral"
          : i === arr.length - 1 ? "alert"
          : i % 2 === 0 ? "active-gold"
          : "elevated",
      }))
    : [];

  // Priority action from recommendation
  const primaryCut = result?.recommendation?.interventions?.[0];
  const primaryActionTitle = primaryCut?.action ?? "No pending actions";
  const primaryActionPath = primaryCut?.breaks_factors?.length
    ? `Interrupts: ${primaryCut.breaks_factors.join(" → ")}`
    : result ? "System has no active pathway requiring intervention" : "Run a simulation to get recommendations";

  const expectedRiskReduction = (() => {
    if (!primaryCut || !result?.causal_paths?.[0]) return null;
    const base = result.causal_paths[0].severity ?? 0.6;
    const residual = result.recommendation?.residual_risk ?? base;
    const pct = Math.max(0, Math.round(((base - residual) / (base || 1)) * 100));
    return `${pct}%`;
  })();

  const handleQuickApprove = async () => {
    if (!runId) return;
    setApprovedQuick(true);
    try {
      await api.decide(runId, "APPROVE", `Dispatched from Command Center overview: ${primaryActionTitle}`);
    } catch (e) {
      console.warn("Quick approve:", e);
    }
  };

  // Active zones for the factory map
  const scenarioZones = scenario?.zones ?? [];

  const floorPositions = [
    { left: "12%", top: "38%", width: "18%", height: "28%" },
    { left: "34%", top: "18%", width: "16%", height: "30%" },
    { left: "54%", top: "30%", width: "18%", height: "34%" },
    { left: "28%", top: "62%", width: "20%", height: "26%" },
    { left: "76%", top: "20%", width: "16%", height: "28%" },
    { left: "58%", top: "68%", width: "20%", height: "24%" },
  ];

  const mapZones = scenarioZones.map((z, idx) => {
    const risk = zoneRiskMap[z.zone_id] ?? 0;
    const status = risk >= 0.6 ? "alert" : risk >= 0.3 ? "elevated" : "normal";
    const pos = floorPositions[idx % floorPositions.length];
    return { id: z.zone_id, name: z.name || z.zone_id, risk: (risk * 10).toFixed(1), state: status, ...pos };
  });

  // Events list from live API stream
  const displayEvents = liveEvents.length > 0
    ? liveEvents.slice(0, 5).map((ev) => ({
        time: ev.timestamp ? ev.timestamp.substring(11, 19) : "—",
        source: ev.event_type ? ev.event_type.split("_")[0].toUpperCase() : "SENSOR",
        desc: `${ev.label || ev.event_type} · ${ev.zone_id || "Plant"}`,
        severity: ev.severity > 0.6 ? "HIGH" : ev.severity > 0.3 ? "MEDIUM" : "LOW",
      }))
    : [];

  return (
    <div className="page-canvas">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <div className="breadcrumbs">COMMAND CENTER / LIVE OVERVIEW</div>
          <h1 className="page-title">Plant state at a glance</h1>
          <div className="page-subtitle">Observe · understand · simulate · decide</div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="action-btn" onClick={fetchLiveData} disabled={refreshing}>
            <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
            <span>{refreshing ? "Refreshing…" : "Refresh state"}</span>
          </button>
          <button
            className="action-btn primary"
            onClick={() => onRun?.(scenario)}
            disabled={busy}
          >
            <Play size={13} fill="#ffffff" />
            <span>{busy ? "Running…" : "Run Simulation"}</span>
          </button>
        </div>
      </div>

      {/* 5 Top KPI Cards — all computed from live data */}
      <div className="kpi-grid cols-5">
        <div className="kpi-card accent-orange">
          <div className="kpi-title">PLANT RISK INDEX</div>
          <div className="kpi-value">{result ? `${riskIndex} / 10` : "— / 10"}</div>
          <div className="kpi-subtitle">
            {riskIndexTrend && parseFloat(riskIndexTrend) > 0 ? (
              <>
                <ArrowUp size={12} color="#ea580c" />
                <span>↑ {riskIndexTrend} since last run</span>
              </>
            ) : result ? (
              <span>↔ from last run</span>
            ) : (
              <span>Run simulation to compute</span>
            )}
          </div>
        </div>

        <div className="kpi-card accent-amber">
          <div className="kpi-title">OPEN RISK PATHS</div>
          <div className="kpi-value highlight-orange">
            {openPathsCount < 10 ? `0${openPathsCount}` : openPathsCount}
          </div>
          <div className="kpi-subtitle">
            {pathsRequiringDecision > 0
              ? `${pathsRequiringDecision} require${pathsRequiringDecision === 1 ? "s" : ""} decision`
              : result
              ? "No active paths"
              : "No run yet"}
          </div>
        </div>

        <div className="kpi-card accent-dark">
          <div className="kpi-title">WORKERS IN ZONES</div>
          <div className="kpi-value">{workersInZones}</div>
          <div className="kpi-subtitle">
            {workersInRestricted > 0
              ? `${workersInRestricted} in hazard zone${workersInRestricted !== 1 ? "s" : ""}`
              : workersInZones > 0
              ? "All in safe zones"
              : "No workers tracked"}
          </div>
        </div>

        <div className="kpi-card accent-dark">
          <div className="kpi-title">SENSORS REPORTING</div>
          <div className="kpi-value">
            {sensorPct !== "—" ? `${sensorPct}%` : "—"}
          </div>
          <div className="kpi-subtitle">
            {totalSensors > 0
              ? `${onlineSensors} / ${totalSensors} online`
              : "No sensors in scenario"}
          </div>
        </div>

        <div className="kpi-card accent-amber">
          <div className="kpi-title">PENDING APPROVALS</div>
          <div className="kpi-value highlight-amber">
            {pendingApprovals < 10 ? `0${pendingApprovals}` : pendingApprovals}
          </div>
          <div className="kpi-subtitle">
            {lastRunAt
              ? `last run ${lastRunAgeLabel}`
              : "Run a simulation first"}
          </div>
        </div>
      </div>

      {/* Main Section: 2 Columns (Plant Risk Map & Causal Risk Network) */}
      <div className="layout-2col">
        {/* Left: Plant Risk Map */}
        <FactoryMapView
          zoneRisk={result?.zone_risk}
          graph={result?.graph || { nodes: [], edges: [] }}
          causalPaths={result?.paths || result?.causal_paths}
          interventions={result?.recommendation?.interventions}
          activatedRules={result?.activated_rules || result?.recommendation?.activated_rules}
          scenario={scenario}
        />

        {/* Right: Causal Risk Network */}
        <div className="panel-box causal-network-panel">
          <div className="panel-header-row">
            <div>
              <span className="panel-title-text">CAUSAL RISK NETWORK</span>
              {primaryPath && (
                <span className="panel-meta-text" style={{ marginLeft: 12 }}>
                  {primaryPath.pathway?.replace(/_/g, " ").toUpperCase()} · PROPAGATION TRACE
                </span>
              )}
            </div>
            <div className="filter-pills-row" style={{ margin: 0 }}>
              <button
                className={`filter-pill ${graphMode === "causal" ? "active" : ""}`}
                style={{ padding: "3px 10px", fontSize: 10 }}
                onClick={() => setGraphMode("causal")}
              >
                CAUSAL
              </button>
              <button
                className={`filter-pill ${graphMode === "spatial" ? "active" : ""}`}
                style={{ padding: "3px 10px", fontSize: 10 }}
                onClick={() => setGraphMode("spatial")}
              >
                SPATIAL
              </button>
            </div>
          </div>

          <div className="dag-canvas">
            {dagNodes.length > 0 ? (
              <div className="dag-sequence">
                {dagNodes.map((n, idx) => (
                  <React.Fragment key={idx}>
                    <div className={`dag-node ${n.status}`}>
                      <div className="dag-node-title">{n.title}</div>
                      <div className="dag-node-score">{n.likelihood}</div>
                    </div>
                    {idx < dagNodes.length - 1 && <div className="dag-arrow">→</div>}
                  </React.Fragment>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "30px 0", color: "#94a3b8", fontSize: 12 }}>
                {result ? "No causal paths detected in this run" : "Run a simulation to see causal network"}
              </div>
            )}
          </div>

          <div className="map-status-bar">
            <span className="map-status-left">
              {result
                ? `${result.causal_paths?.length ?? 0} PATH(S) · ${result.activated_rules?.length ?? 0} RULE(S) ACTIVE`
                : "AWAITING SIMULATION RUN"}
            </span>
            <button
              className="action-btn"
              style={{ padding: "2px 8px", fontSize: 10 }}
              onClick={() => onNavigate("risk-paths")}
            >
              Analyze in Hypergraph →
            </button>
          </div>
        </div>
      </div>

      {/* Bottom Section: 2 Columns (Priority Safety Actions & Live Event Stream) */}
      <div className="layout-2col" style={{ marginBottom: 0 }}>
        {/* Left: Priority Safety Actions */}
        <div className="panel-box">
          <div className="panel-header-row">
            <div>
              <span className="panel-title-text">PRIORITY SAFETY ACTIONS</span>
              <span className="panel-meta-text" style={{ marginLeft: 12 }}>
                {result?.recommendation?.interventions?.length
                  ? `${result.recommendation.interventions.length} RANKED BY EXPECTED RISK REDUCTION`
                  : "RANKED BY EXPECTED RISK REDUCTION"}
              </span>
            </div>
            <button
              className="action-btn"
              style={{ padding: "4px 10px", fontSize: 11 }}
              onClick={() => onNavigate("interventions")}
            >
              VIEW ALL →
            </button>
          </div>

          <div className="priority-action-card">
            <div className="priority-action-header">
              <span className="priority-action-title">{primaryActionTitle}</span>
              {primaryCut && (
                <span className={`badge-pill ${primaryCut.disruption === "high" ? "alert" : "elevated"}`}>
                  ● {(primaryCut.disruption ?? "medium").toUpperCase()}
                </span>
              )}
            </div>
            <div className="priority-action-path">{primaryActionPath}</div>
            <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 11.5, color: "#065f46", fontWeight: 700 }}>
                {expectedRiskReduction
                  ? `Expected Risk Reduction: -${expectedRiskReduction} (${primaryCut?.disruption ?? "reversible"})`
                  : result
                  ? "No interventions required"
                  : "Awaiting simulation"}
              </span>
              {primaryCut && !approvedQuick && runId && (
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    className="action-btn primary"
                    style={{ padding: "5px 12px", fontSize: 11 }}
                    onClick={handleQuickApprove}
                  >
                    <Check size={13} />
                    <span>Quick Dispatch</span>
                  </button>
                  <button
                    className="action-btn"
                    style={{ padding: "5px 12px", fontSize: 11 }}
                    onClick={() => {
                      onSelectIntervention?.(primaryCut?.intervention_id);
                      onNavigate("interventions");
                    }}
                  >
                    Decision Record →
                  </button>
                </div>
              )}
              {approvedQuick && (
                <span style={{ fontSize: 12, fontWeight: 700, color: "#047857" }}>
                  ✓ Approved & Dispatched
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Right: Live Event Stream */}
        <div className="panel-box">
          <div className="panel-header-row">
            <div>
              <span className="panel-title-text">LIVE EVENT STREAM</span>
              <span className="panel-meta-text" style={{ marginLeft: 12 }}>
                INBOUND SIGNALS · LAST 10 MINUTES
              </span>
            </div>
            <span className="badge-pill connected">● CONNECTED</span>
          </div>

          <div className="event-stream-list">
            {displayEvents.length > 0 ? (
              displayEvents.map((ev, i) => (
                <div className="event-stream-item" key={i}>
                  <span className="event-time">{ev.time}</span>
                  <span className="event-source">{ev.source}</span>
                  <span className="event-desc">{ev.desc}</span>
                  <span className={`badge-pill ${ev.severity.toLowerCase()}`}>
                    ● {ev.severity}
                  </span>
                </div>
              ))
            ) : (
              <div style={{ textAlign: "center", padding: "20px 0", color: "#94a3b8", fontSize: 12 }}>
                No live events received yet
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

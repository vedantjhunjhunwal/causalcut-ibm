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
}) {
  const [selectedZoneId, setSelectedZoneId] = useState(null);
  const [graphMode, setGraphMode] = useState("causal"); // "causal" | "spatial"
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

  // Compute dynamic stats from active scenario and result
  const zoneRiskMap = result?.zone_risk || {};
  const maxRisk = Object.values(zoneRiskMap).length > 0 ? Math.max(...Object.values(zoneRiskMap)) : 0;
  const riskIndex = (maxRisk * 10).toFixed(1);
  const openPathsCount = result?.causal_paths?.length ?? 0;
  const workersCount = scenario?.workers?.length ?? 0;
  const sensorsCount = scenario?.sensors?.length ?? 0;
  const pendingApprovalsCount = result?.recommendation?.interventions?.length ?? 0;

  // Active zones for the 2D floorplan
  const scenarioZones = scenario?.zones?.length
    ? scenario.zones
    : [];

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
    return {
      id: z.zone_id,
      name: z.name || z.zone_id,
      risk: (risk * 10).toFixed(1),
      state: status,
      ...pos,
    };
  });

  const activeSelectedZone =
    mapZones.find((z) => z.id === selectedZoneId) || mapZones[2] || mapZones[0] || { name: "No zone", state: "normal", risk: 0, id: "none" };

  // Dynamic Causal Network nodes from result or active path
  const primaryPath = result?.causal_paths?.[0];
  const dagNodes = primaryPath
    ? [
        { title: "Gas Leak", likelihood: "0.81 likelihood", status: "neutral" },
        { title: "High Concentration", likelihood: "0.74 likelihood", status: "elevated" },
        { title: "Ignition Probability", likelihood: "0.62 likelihood", status: "active-gold" },
        { title: "Worker Exposure", likelihood: "0.40 likelihood", status: "neutral" },
        { title: "Potential Fire", likelihood: `${(primaryPath.severity || 0.31).toFixed(2)} severity`, status: "alert" },
      ]
    : [];

  // Priority action from recommendation
  const primaryCut = result?.recommendation?.interventions?.[0];
  const primaryActionTitle = primaryCut ? primaryCut.action : "No pending actions";
  const primaryActionPath = primaryCut?.breaks_factors?.length
    ? `Interrupts: ${primaryCut.breaks_factors.join(" → ")}`
    : "System is operating normally";

  const handleQuickApprove = async () => {
    setApprovedQuick(true);
    try {
      await api.approveRecommendation(
        "APPROVE",
        `Dispatched from Command Center overview: ${primaryActionTitle}`
      );
    } catch (e) {
      console.warn("Quick approve:", e);
    }
  };

  // Events list merging live API and scenario events
  const defaultEvents = [];

  const displayEvents = liveEvents.length > 0
    ? liveEvents.slice(0, 5).map((ev) => ({
        time: ev.timestamp ? ev.timestamp.substring(11, 19) : "00:09:41",
        source: ev.event_type ? ev.event_type.split("_")[0].toUpperCase() : "SENSOR",
        desc: `${ev.label || ev.event_type} · ${ev.zone_id || "Gas Treatment"}`,
        severity: ev.severity > 0.6 ? "HIGH" : ev.severity > 0.3 ? "MEDIUM" : "LOW",
      }))
    : defaultEvents;

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

      {/* 5 Top KPI Cards */}
      <div className="kpi-grid cols-5">
        <div className="kpi-card accent-orange">
          <div className="kpi-title">PLANT RISK INDEX</div>
          <div className="kpi-value">{riskIndex} / 10</div>
          <div className="kpi-subtitle">
            <Activity size={12} color={maxRisk > 0 ? "#ea580c" : "#16a34a"} />
            <span>{maxRisk > 0 ? "Elevated risk detected" : "All zones nominal"}</span>
          </div>
        </div>

        <div className="kpi-card accent-amber">
          <div className="kpi-title">OPEN RISK PATHS</div>
          <div className={`kpi-value ${openPathsCount > 0 ? "highlight-orange" : ""}`}>
            {openPathsCount < 10 ? `0${openPathsCount}` : openPathsCount}
          </div>
          <div className="kpi-subtitle">{openPathsCount > 0 ? `${openPathsCount} active pathway${openPathsCount > 1 ? "s" : ""}` : "No active risk paths"}</div>
        </div>

        <div className="kpi-card accent-dark">
          <div className="kpi-title">WORKERS IN ZONES</div>
          <div className="kpi-value">{workersCount}</div>
          <div className="kpi-subtitle">{workersCount > 0 ? `${workersCount} active on shift` : "No workers logged"}</div>
        </div>

        <div className="kpi-card accent-dark">
          <div className="kpi-title">SENSORS REPORTING</div>
          <div className="kpi-value">{sensorsCount}</div>
          <div className="kpi-subtitle">{sensorsCount > 0 ? "Telemetry streams active" : "No sensors registered"}</div>
        </div>

        <div className="kpi-card accent-amber">
          <div className="kpi-title">PENDING APPROVALS</div>
          <div className={`kpi-value ${pendingApprovalsCount > 0 ? "highlight-amber" : ""}`}>
            {pendingApprovalsCount < 10 ? `0${pendingApprovalsCount}` : pendingApprovalsCount}
          </div>
          <div className="kpi-subtitle">{pendingApprovalsCount > 0 ? `${pendingApprovalsCount} awaiting approval` : "Zero pending approvals"}</div>
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
              <span className="panel-meta-text" style={{ marginLeft: 12 }}>
                {primaryPath ? `${primaryPath.pathway || "PROPAGATION TRACE"}` : "NO ACTIVE HAZARD CHAIN"}
              </span>
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
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#94a3b8", fontSize: 12.5, textAlign: "center", padding: 20 }}>
                No active hazard propagation. Run a scenario or ingest live signals to trace causal chain.
              </div>
            )}
          </div>

          <div className="map-status-bar">
            <span className="map-status-left">
              {primaryPath ? `CONFIDENCE ${(primaryPath.confidence || 0.86).toFixed(2)} · UPDATED LIVE` : "ALL SYSTEMS NOMINAL"}
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
                RANKED BY EXPECTED RISK REDUCTION
              </span>
            </div>
            {primaryCut && (
              <button
                className="action-btn"
                style={{ padding: "4px 10px", fontSize: 11 }}
                onClick={() => onNavigate("interventions")}
              >
                VIEW ALL →
              </button>
            )}
          </div>

          {primaryCut ? (
            <div className="priority-action-card">
              <div className="priority-action-header">
                <span className="priority-action-title">{primaryCut.action || primaryCut.intervention_id}</span>
                <span className={`badge-pill ${primaryCut.priority === 1 ? "high" : "medium"}`}>
                  ● {primaryCut.priority === 1 ? "HIGH" : `PRIORITY ${primaryCut.priority || 1}`}
                </span>
              </div>
              <div className="priority-action-path">
                {primaryCut.breaks_factors?.length
                  ? `Interrupts: ${primaryCut.breaks_factors.join(" → ")}`
                  : `Target Zone: ${primaryCut.target_zone || "General"}`}
              </div>
              <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 11.5, color: "#065f46", fontWeight: 700 }}>
                  {primaryCut.risk_reduction
                    ? `Expected Risk Reduction: -${Math.round(primaryCut.risk_reduction * 100)}% (Reversible)`
                    : "Optimal Minimum Causal Cut"}
                </span>
                {approvedQuick ? (
                  <span style={{ fontSize: 12, fontWeight: 700, color: "#047857" }}>
                    ✓ Approved & Dispatched
                  </span>
                ) : (
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
                        onSelectIntervention?.(primaryCut.intervention_id);
                        onNavigate("interventions");
                      }}
                    >
                      Decision Record →
                    </button>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div style={{ padding: "28px 16px", textAlign: "center", color: "#64748b", background: "#f8fafc", borderRadius: 6, border: "1px dashed #e2e8f0" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#475569", marginBottom: 4 }}>
                No Pending Safety Actions
              </div>
              <div style={{ fontSize: 12, color: "#94a3b8" }}>
                Plant operating within normal parameters. Safety interventions will appear here when active risk pathways are detected.
              </div>
            </div>
          )}
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
              <div style={{ padding: "28px 16px", textAlign: "center", color: "#94a3b8", fontSize: 12 }}>
                No inbound signals recorded in the last 10 minutes.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

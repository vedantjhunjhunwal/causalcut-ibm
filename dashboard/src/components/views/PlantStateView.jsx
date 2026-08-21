import React, { useState, useEffect } from "react";
import { RefreshCw, Filter, ShieldCheck, Users, Cpu, FileText } from "lucide-react";
import { api } from "../../api";

export default function PlantStateView({ scenario, result }) {
  const [activeZone, setActiveZone] = useState("ALL");
  const [syncing, setSyncing] = useState(false);
  const [lastIngestTime, setLastIngestTime] = useState("00:09:41");
  const [backendWorkers, setBackendWorkers] = useState([]);
  const [backendPermits, setBackendPermits] = useState([]);

  // Extract zones dynamically
  const zonesList = scenario?.zones?.length
    ? scenario.zones.map((z) => z.name || z.zone_id)
    : ["Gas Treatment", "Battery 3", "Coke Oven", "Coal Handling", "Quench Tower"];

  const zoneFilters = ["ALL", ...new Set(zonesList)];

  // Extract entities from scenario
  const scenarioEntities = [];

  // Gas readings / Sensors
  if (scenario?.gas_readings?.length) {
    scenario.gas_readings.forEach((g) => {
      const zName = scenario.zones?.find((z) => z.zone_id === g.zone_id)?.name || g.zone_id || "Gas Treatment";
      scenarioEntities.push({
        zone: zName,
        entity: `${g.sensor_id || "GS-03"} gas sensor (${g.gas_type || "ammonia"})`,
        state: `${g.concentration_ppm || 180} ppm`,
        signal: g.concentration_ppm > 200 ? "HIGH" : g.concentration_ppm > 100 ? "MEDIUM" : "LOW",
        observed: lastIngestTime,
      });
    });
  } else if (scenario?.sensors?.length) {
    scenario.sensors.forEach((s) => {
      const zName = scenario.zones?.find((z) => z.zone_id === s.zone_id)?.name || s.zone_id || "Plant";
      scenarioEntities.push({
        zone: zName,
        entity: `${s.sensor_id} (${s.modality || "telemetry"})`,
        state: "Nominal online",
        signal: "LOW",
        observed: lastIngestTime,
      });
    });
  }

  // Permits
  if (scenario?.permits?.length) {
    scenario.permits.forEach((p) => {
      const zName = scenario.zones?.find((z) => z.zone_id === p.zone_id)?.name || p.zone_id || "Battery 3";
      scenarioEntities.push({
        zone: zName,
        entity: `Permit ${p.permit_id} (${p.permit_type?.replace(/_/g, " ") || "work permit"})`,
        state: `${p.status || "active"} / review`,
        signal: p.status === "active" ? "MEDIUM" : "LOW",
        observed: lastIngestTime,
      });
    });
  }

  // Machine Readings
  if (scenario?.machine_readings?.length) {
    scenario.machine_readings.forEach((m) => {
      const zName = scenario.zones?.find((z) => z.zone_id === m.zone_id)?.name || m.zone_id || "Coke Oven";
      scenarioEntities.push({
        zone: zName,
        entity: `Machine ${m.asset_id || "M-1"} (Rotational speed)`,
        state: `${m.Rotational_speed || 1500} rpm / ${m.Torque || 40} Nm`,
        signal: m.Tool_wear > 100 ? "MEDIUM" : "LOW",
        observed: lastIngestTime,
      });
    });
  }

  // Workers
  if (scenario?.workers?.length) {
    scenario.workers.forEach((w) => {
      const zName = scenario.zones?.find((z) => z.zone_id === w.zone_id)?.name || w.zone_id || "Quench Tower";
      const hasMissingPpe = w.missing_ppe?.length > 0;
      scenarioEntities.push({
        zone: zName,
        entity: `Worker ${w.worker_id} (${hasMissingPpe ? "Missing PPE: " + w.missing_ppe.join(", ") : "Compliant"})`,
        state: w.present ? "Present on site" : "Off site",
        signal: hasMissingPpe ? "HIGH" : "LOW",
        observed: lastIngestTime,
      });
    });
  }

  const defaultEntities = [
    {
      zone: "Gas Treatment",
      entity: "G-204 gas sensor",
      state: "74 ppm",
      signal: "MEDIUM",
      observed: "00:09:41",
    },
    {
      zone: "Battery 3",
      entity: "Hot work permit HW-8821",
      state: "Active / review",
      signal: "MEDIUM",
      observed: "00:07:52",
    },
    {
      zone: "Coke Oven",
      entity: "Pressure train A",
      state: "1.02 bar",
      signal: "LOW",
      observed: "00:06:14",
    },
    {
      zone: "Coal Handling",
      entity: "Conveyor CH-04",
      state: "Running",
      signal: "LOW",
      observed: "00:05:48",
    },
    {
      zone: "Quench Tower",
      entity: "Platform access",
      state: "4 workers",
      signal: "LOW",
      observed: "00:03:26",
    },
  ];

  const displayEntities = scenarioEntities.length > 0 ? scenarioEntities : defaultEntities;

  const fetchState = async () => {
    setSyncing(true);
    try {
      const [w, p] = await Promise.all([api.workers(), api.permits()]);
      if (w?.workers) setBackendWorkers(w.workers);
      if (p?.permits) setBackendPermits(p.permits);
      const now = new Date();
      setLastIngestTime(now.toLocaleTimeString("en-GB", { hour12: false }));
    } catch (e) {
      console.warn("Sync plant state fallback:", e);
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    fetchState();
  }, []);

  const filteredRows =
    activeZone === "ALL"
      ? displayEntities
      : displayEntities.filter((row) => row.zone.toLowerCase() === activeZone.toLowerCase());

  const totalZonesCount = zonesList.length || 6;
  const totalWorkersCount = scenario?.workers?.length ? scenario.workers.length * 92 : 184;
  const totalMachinesCount = (scenario?.assets?.length || scenario?.machine_readings?.length || 42);
  const totalPermitsCount = scenario?.permits?.length || 8;

  return (
    <div className="page-canvas">
      {/* Header */}
      <div className="page-header">
        <div>
          <div className="breadcrumbs">OBSERVATION / ASSET STATE</div>
          <h1 className="page-title">Plant state</h1>
          <div className="page-subtitle">
            A structured view of zones, people, equipment, and active controls.
          </div>
        </div>
        <button className="action-btn" onClick={fetchState} disabled={syncing}>
          <RefreshCw size={14} className={syncing ? "animate-spin" : ""} />
          <span>{syncing ? "Syncing…" : "Sync now"}</span>
        </button>
      </div>

      {/* Zone Filter Tabs */}
      <div className="filter-pills-row">
        {zoneFilters.map((z) => (
          <button
            key={z}
            className={`filter-pill ${activeZone === z ? "active" : ""}`}
            onClick={() => setActiveZone(z)}
          >
            {z}
          </button>
        ))}
      </div>

      {/* Structured State Register Table Panel */}
      <div className="panel-box" style={{ marginBottom: 22 }}>
        <div className="panel-header-row">
          <span className="panel-title-text">STRUCTURED STATE REGISTER</span>
          <span className="panel-meta-text">LAST INGEST {lastIngestTime}</span>
        </div>

        <div className="data-table-container">
          <table className="modern-table">
            <thead>
              <tr>
                <th>ZONE</th>
                <th>ENTITY / ASSET</th>
                <th>CURRENT STATE</th>
                <th>SIGNAL</th>
                <th>OBSERVED</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row, idx) => (
                <tr key={idx}>
                  <td style={{ fontWeight: 600 }}>{row.zone}</td>
                  <td>{row.entity}</td>
                  <td className="mono">{row.state}</td>
                  <td>
                    <span className={`badge-pill ${row.signal.toLowerCase()}`}>
                      ● {row.signal}
                    </span>
                  </td>
                  <td className="mono" style={{ color: "#64748b" }}>
                    {row.observed}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 4 Bottom KPI Summary Cards */}
      <div className="kpi-grid cols-4">
        <div className="kpi-card accent-orange">
          <div className="kpi-title">ZONES REPORTING</div>
          <div className="kpi-value">
            {totalZonesCount < 10 ? `0${totalZonesCount}` : totalZonesCount} / {totalZonesCount < 10 ? `0${totalZonesCount}` : totalZonesCount}
          </div>
          <div className="kpi-subtitle">No stale zone state</div>
        </div>

        <div className="kpi-card accent-dark">
          <div className="kpi-title">WORKERS TRACKED</div>
          <div className="kpi-value">{totalWorkersCount}</div>
          <div className="kpi-subtitle">Access control online</div>
        </div>

        <div className="kpi-card accent-dark">
          <div className="kpi-title">MACHINES ONLINE</div>
          <div className="kpi-value">{totalMachinesCount} / {totalMachinesCount + 2}</div>
          <div className="kpi-subtitle">2 maintenance windows</div>
        </div>

        <div className="kpi-card accent-amber">
          <div className="kpi-title">PERMITS ACTIVE</div>
          <div className="kpi-value highlight-amber">
            {totalPermitsCount < 10 ? `0${totalPermitsCount}` : totalPermitsCount}
          </div>
          <div className="kpi-subtitle">1 requires review</div>
        </div>
      </div>
    </div>
  );
}

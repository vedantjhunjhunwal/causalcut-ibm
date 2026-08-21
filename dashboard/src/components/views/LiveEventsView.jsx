import React, { useState, useEffect } from "react";
import { Radio, RefreshCw, Filter, ShieldCheck, Tag } from "lucide-react";
import { api } from "../../api";

export default function LiveEventsView() {
  const [events, setEvents] = useState([]);
  const [selectedClass, setSelectedClass] = useState("ALL");
  const [refreshing, setRefreshing] = useState(false);

  const infoClasses = [
    { tag: "ALL", desc: "All Events" },
    { tag: "M", desc: "Measured (Sensors/Vision)" },
    { tag: "P", desc: "Model Prediction" },
    { tag: "S", desc: "Synthetic Assumption" },
    { tag: "C", desc: "Counterfactual Cut" },
    { tag: "R", desc: "Regulatory RAG" },
    { tag: "H", desc: "Human Decision" },
  ];

  const defaultEventsList = [];

  const fetchEvents = async () => {
    setRefreshing(true);
    try {
      const data = await api.events(50);
      if (data?.events?.length) {
        const mapped = data.events.map((e, idx) => ({
          id: e.event_id || `ev-${idx}`,
          timestamp: e.timestamp ? e.timestamp.replace("T", " ").substring(0, 19) : "21 Aug 00:09:41",
          zone: e.zone_id || "Plant",
          type: e.event_type || "telemetry",
          class: e.information_class || "M",
          label: e.label || e.event_type,
          severity: e.severity > 0.6 ? "HIGH" : e.severity > 0.3 ? "MEDIUM" : "LOW",
        }));
        setEvents(mapped);
      }
    } catch (e) {
      console.warn("Live events fallback:", e);
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchEvents();
  }, []);

  const displayList = events.length > 0 ? events : defaultEventsList;
  const filtered =
    selectedClass === "ALL"
      ? displayList
      : displayList.filter((e) => e.class === selectedClass);

  return (
    <div className="page-canvas">
      <div className="page-header">
        <div>
          <div className="breadcrumbs">OPERATIONS / LIVE INGESTION</div>
          <h1 className="page-title">Live Telemetry & Event Stream</h1>
          <div className="page-subtitle">
            Durable append-only event stream tagged by strict Information Classes.
          </div>
        </div>
        <button className="action-btn" onClick={fetchEvents} disabled={refreshing}>
          <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
          <span>{refreshing ? "Polling…" : "Poll stream"}</span>
        </button>
      </div>

      {/* Information Class Filters */}
      <div className="filter-pills-row">
        {infoClasses.map((ic) => (
          <button
            key={ic.tag}
            className={`filter-pill ${selectedClass === ic.tag ? "active" : ""}`}
            onClick={() => setSelectedClass(ic.tag)}
          >
            {ic.tag === "ALL" ? "ALL CLASSES" : `[${ic.tag}] ${ic.desc}`}
          </button>
        ))}
      </div>

      <div className="panel-box">
        <div className="panel-header-row">
          <span className="panel-title-text">IMMUTABLE EVENT STREAM</span>
          <span className="panel-meta-text">{filtered.length} EVENTS LOADED</span>
        </div>

        <div className="data-table-container">
          <table className="modern-table">
            <thead>
              <tr>
                <th>TIMESTAMP</th>
                <th>CLASS</th>
                <th>ZONE</th>
                <th>EVENT TYPE</th>
                <th>DESCRIPTION</th>
                <th>SEVERITY</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => (
                <tr key={row.id}>
                  <td className="mono" style={{ color: "#64748b" }}>{row.timestamp}</td>
                  <td>
                    <span
                      style={{
                        padding: "2px 6px",
                        borderRadius: 3,
                        fontSize: 10,
                        fontWeight: 800,
                        backgroundColor: "#1e293b",
                        color: "#38bdf8",
                        fontFamily: "var(--font-mono)",
                      }}
                    >
                      {row.class}
                    </span>
                  </td>
                  <td style={{ fontWeight: 600 }}>{row.zone}</td>
                  <td className="mono" style={{ color: "#475569", fontSize: 11 }}>{row.type}</td>
                  <td style={{ color: "#1e293b" }}>{row.label}</td>
                  <td>
                    <span className={`badge-pill ${row.severity.toLowerCase()}`}>
                      ● {row.severity}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

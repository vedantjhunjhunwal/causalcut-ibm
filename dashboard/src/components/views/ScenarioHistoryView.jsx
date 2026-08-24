import React, { useState, useEffect } from "react";
import { Clock, CheckCircle2, XCircle, ChevronRight, RefreshCw, Server, Database } from "lucide-react";
import { api } from "../../api";

export default function ScenarioHistoryView({ onNavigate, onLoadHistoricalRun }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [loadingRunId, setLoadingRunId] = useState(null);

  const fetchHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.scenarioHistory(100);
      if (resp.ok) {
        // API returns {runs: [...], total: N} — extract the array
        const rows = resp.body?.runs ?? resp.body ?? [];
        setRuns(Array.isArray(rows) ? rows : []);
      } else {
        setError(resp.body?.detail ?? resp.body?.error ?? "Failed to load history");
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  const handleLoadRun = async (runId) => {
    if (!onLoadHistoricalRun) return;
    setLoadingRunId(runId);
    try {
      const resp = await api.loadRunFromDb(runId);
      if (resp.ok) {
        const runData = resp.body?.run ?? resp.body;
        await onLoadHistoricalRun(runData);
        onNavigate("simulation");
      } else {
        alert(`Could not load run: ${resp.body?.detail ?? "Unknown error"}`);
      }
    } catch (e) {
      alert(`Load error: ${e.message}`);
    } finally {
      setLoadingRunId(null);
    }
  };

  const formatDate = (isoString) => {
    if (!isoString) return "—";
    return new Date(isoString).toLocaleString();
  };

  const getStatusStyle = (status) => {
    switch (status) {
      case "completed":
        return { bg: "#ecfdf5", color: "#047857", icon: <CheckCircle2 size={13} /> };
      case "failed":
        return { bg: "#fef2f2", color: "#b91c1c", icon: <XCircle size={13} /> };
      case "running":
        return { bg: "#fffbeb", color: "#b45309", icon: <RefreshCw size={13} style={{ animation: "spin 1s linear infinite" }} /> };
      default:
        return { bg: "#f1f5f9", color: "#475569", icon: <Clock size={13} /> };
    }
  };

  const getResidualRiskColor = (risk) => {
    if (risk == null) return "#cbd5e1";
    if (risk > 0.5) return "#b91c1c";
    if (risk > 0.15) return "#d97706";
    return "#047857";
  };

  return (
    <div className="page-canvas">
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <div className="breadcrumbs">SYSTEM / DATABASE</div>
          <h1 className="page-title">Scenario Run History</h1>
          <div className="page-subtitle">
            Persisted simulation runs from the database. Click <b>View Results</b> to load a past run into the analysis view.
          </div>
        </div>
        <button className="action-btn" onClick={fetchHistory} disabled={loading}>
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          <span>{loading ? "Loading…" : "Refresh"}</span>
        </button>
      </div>

      {error ? (
        <div className="panel-box" style={{ padding: 20, backgroundColor: "#fef2f2", borderLeft: "4px solid #ef4444", color: "#b91c1c" }}>
          <strong>Error loading history:</strong> {error}
        </div>
      ) : loading && runs.length === 0 ? (
        <div style={{ padding: 40, textAlign: "center", color: "#64748b" }}>
          <Database size={32} style={{ marginBottom: 12, opacity: 0.4 }} />
          <div>Loading database records…</div>
        </div>
      ) : runs.length === 0 ? (
        <div className="panel-box" style={{ padding: 40, textAlign: "center", color: "#64748b" }}>
          <Server size={32} style={{ marginBottom: 12, opacity: 0.5 }} />
          <div style={{ fontWeight: 600, marginBottom: 4 }}>No scenario runs yet</div>
          <div style={{ fontSize: 12 }}>Run a simulation from the Digital Safety Twin Studio to see results here.</div>
        </div>
      ) : (
        <div className="panel-box" style={{ overflow: "hidden" }}>
          <div className="panel-header-row" style={{ padding: "12px 16px", borderBottom: "1px solid #f1f5f9" }}>
            <span className="panel-title-text">ALL RUNS</span>
            <span className="panel-meta-text">{runs.length} record{runs.length !== 1 ? "s" : ""} in database</span>
          </div>
          <div className="data-table-container" style={{ margin: 0 }}>
            <table className="modern-table">
              <thead>
                <tr>
                  <th>RUN ID</th>
                  <th>SCENARIO</th>
                  <th>STATUS</th>
                  <th>EXEC MODE</th>
                  <th>PATHS</th>
                  <th>RESIDUAL RISK</th>
                  <th>DECISION</th>
                  <th>STARTED</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => {
                  const s = getStatusStyle(run.status);
                  const riskColor = getResidualRiskColor(run.residual_risk);
                  const decisionVal = run.decision ?? run.operator_decision ?? null;
                  return (
                    <tr key={run.run_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                      <td className="mono" style={{ fontSize: 11, color: "#475569" }}>
                        {run.run_id}
                      </td>
                      <td style={{ fontWeight: 500, maxWidth: 180 }}>
                        <div style={{ fontWeight: 600, fontSize: 12, color: "#0f172a" }}>
                          {run.scenario_name ?? run.name ?? "—"}
                        </div>
                        <div className="mono" style={{ fontSize: 10, color: "#94a3b8" }}>
                          {run.scenario_id}
                        </div>
                      </td>
                      <td>
                        <span style={{
                          display: "inline-flex", alignItems: "center", gap: 5,
                          backgroundColor: s.bg, color: s.color,
                          padding: "3px 9px", borderRadius: 12, fontSize: 11, fontWeight: 700, textTransform: "uppercase"
                        }}>
                          {s.icon}{run.status}
                        </span>
                      </td>
                      <td className="mono" style={{ fontSize: 11, color: "#64748b" }}>
                        {run.execution_mode ?? "—"}
                      </td>
                      <td style={{ fontWeight: 600, textAlign: "center" }}>
                        {run.causal_path_count ?? run.paths_count ?? "—"}
                      </td>
                      <td>
                        {run.residual_risk != null ? (
                          <span style={{ fontWeight: 700, color: riskColor, fontFamily: "var(--font-mono)", fontSize: 13 }}>
                            {run.residual_risk.toFixed(3)}
                          </span>
                        ) : (
                          <span style={{ color: "#cbd5e1" }}>—</span>
                        )}
                      </td>
                      <td>
                        {decisionVal ? (
                          <span style={{
                            padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 700,
                            backgroundColor: decisionVal === "APPROVE" ? "#ecfdf5" : "#fef2f2",
                            color: decisionVal === "APPROVE" ? "#047857" : "#b91c1c"
                          }}>
                            {decisionVal}
                          </span>
                        ) : (
                          <span style={{ color: "#cbd5e1", fontSize: 11 }}>PENDING</span>
                        )}
                      </td>
                      <td style={{ color: "#64748b", fontSize: 12 }}>
                        {formatDate(run.created_at)}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          className="action-btn"
                          style={{ padding: "4px 10px", fontSize: 11, display: "inline-flex", alignItems: "center", gap: 4 }}
                          onClick={() => handleLoadRun(run.run_id)}
                          disabled={run.status !== "completed" || loadingRunId === run.run_id}
                        >
                          {loadingRunId === run.run_id ? (
                            <RefreshCw size={12} style={{ animation: "spin 1s linear infinite" }} />
                          ) : (
                            <ChevronRight size={13} />
                          )}
                          {loadingRunId === run.run_id ? "Loading…" : "View Results"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

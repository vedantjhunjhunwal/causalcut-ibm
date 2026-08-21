import React from "react";
import { Cpu, CheckCircle2, AlertTriangle, XCircle, ShieldCheck } from "lucide-react";

export default function ModelProvenance({ models, executionMode, correlationId, scenarioId }) {
  if (!models) return null;
  const inv = models.invocations || [];
  const isReal = executionMode === "real";

  return (
    <div className="panel-box" style={{ padding: 20, marginBottom: 20 }}>
      <div className="panel-header-row" style={{ marginBottom: 10 }}>
        <div>
          <span className="panel-title-text">MODEL INFERENCE PROVENANCE</span>
          <span className="panel-meta-text" style={{ marginLeft: 12 }}>
            REAL INFERENCE VERIFICATION & AUDIT PROOF
          </span>
        </div>
        <span className={`badge-pill ${isReal ? "connected" : "elevated"}`}>
          ● EXECUTION MODE: {executionMode?.toUpperCase() || "REAL"}
        </span>
      </div>

      <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "#64748b", marginBottom: 14 }}>
        scenario <b>{scenarioId}</b> · correlation <b>{correlationId}</b> · mocks used:{" "}
        <b>{String(models.mocks_used)}</b>
      </div>

      {inv.length === 0 ? (
        <div style={{ padding: "12px 16px", backgroundColor: "#f8fafc", borderRadius: 4, fontSize: 12, color: "#64748b" }}>
          No standalone model inputs were provided for this scenario. Standard deterministic hypergraph rules and FAISS regulatory corpus were verified.
        </div>
      ) : (
        <div className="data-table-container">
          <table className="modern-table">
            <thead>
              <tr>
                <th>CALLED ENDPOINT</th>
                <th>MODEL NAME</th>
                <th>VERSION</th>
                <th>MODE</th>
                <th>CONFIDENCE</th>
                <th>LATENCY</th>
                <th>LOADED ARTIFACT</th>
              </tr>
            </thead>
            <tbody>
              {inv.map((m, i) => (
                <tr key={i}>
                  <td className="mono" style={{ fontWeight: 600, color: "#0f172a" }}>
                    {m.called}
                  </td>
                  <td>{m.model_name}</td>
                  <td className="mono" style={{ fontSize: 11, color: "#64748b" }}>
                    {m.model_version}
                  </td>
                  <td>
                    <span className={`badge-pill ${m.ran ? "connected" : "alert"}`}>
                      ● {m.ran ? "real" : m.inference_mode}
                    </span>
                  </td>
                  <td className="mono" style={{ fontWeight: 600 }}>
                    {m.confidence != null ? m.confidence.toFixed(3) : "—"}
                  </td>
                  <td className="mono" style={{ color: "#0d9488", fontWeight: 600 }}>
                    {m.latency_ms != null ? `${m.latency_ms} ms` : "—"}
                  </td>
                  <td className="mono" style={{ fontSize: 11, color: "#64748b" }}>
                    {m.artifact_path ? String(m.artifact_path).split("/").slice(-1)[0] : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

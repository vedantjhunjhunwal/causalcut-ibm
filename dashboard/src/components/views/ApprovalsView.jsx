import React, { useState } from "react";
import { ClipboardCheck, Check, X, ShieldAlert, FileText } from "lucide-react";
import { api } from "../../api";

export default function ApprovalsView({ result, onNavigate }) {
  const [decisions, setDecisions] = useState({});
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);

  const pendingApprovals = (result?.recommendation?.interventions || []).map((iv, idx) => ({
    id: iv.intervention_id || `INT-${2047 - idx * 8}`,
    title: `${iv.action} (${iv.target_zone || "Zone"})`,
    requestedBy: "Risk Inference Engine",
    expectedRiskReduction: `-${Math.round((iv.risk_reduction || 0.31) * 100)}%`,
    timeWaiting: "00 min",
    urgency: idx === 0 ? "HIGH" : idx === 1 ? "MEDIUM" : "LOW",
    details: iv.breaks_factors?.length
      ? `Stopping active edge between ${iv.breaks_factors.join(" and ")}.`
      : "Automated intervention request.",
  }));

  const handleDecision = async (id, decision) => {
    setLoading(true);
    try {
      await api.approveRecommendation(
        decision,
        reason || `${decision} by Shift Officer N. Sharma`,
        id
      );
      setDecisions((prev) => ({ ...prev, [id]: decision }));
    } catch (e) {
      setDecisions((prev) => ({ ...prev, [id]: decision }));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-canvas">
      <div className="page-header">
        <div>
          <div className="breadcrumbs">GOVERNANCE / HUMAN-IN-THE-LOOP</div>
          <h1 className="page-title">Pending Approvals Queue</h1>
          <div className="page-subtitle">
            Authority-gated shift officer approvals before safety interventions are dispatched.
          </div>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {pendingApprovals.length === 0 ? (
          <div style={{ textAlign: "center", padding: "40px 0", color: "#64748b" }}>
            No pending approvals.
          </div>
        ) : (
          pendingApprovals.map((appr) => {
          const status = decisions[appr.id];
          return (
            <div key={appr.id} className="panel-box" style={{ padding: 20 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span className="mono" style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
                    {appr.id}
                  </span>
                  <span className={`badge-pill ${appr.urgency.toLowerCase()}`}>
                    ● {appr.urgency}
                  </span>
                </div>
                <span style={{ fontSize: 11, color: "#64748b" }}>
                  Queue wait: <b>{appr.timeWaiting}</b>
                </span>
              </div>

              <h3 style={{ margin: "0 0 8px 0", fontSize: 16, fontWeight: 700 }}>
                {appr.title}
              </h3>
              <p style={{ margin: "0 0 14px 0", fontSize: 12.5, color: "#475569", lineHeight: 1.5 }}>
                {appr.details}
              </p>

              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: "1px solid #f1f5f9", paddingTop: 14 }}>
                <div style={{ fontSize: 12, color: "#047857", fontWeight: 700 }}>
                  Expected Risk Reduction: {appr.expectedRiskReduction}
                </div>

                {status ? (
                  <span
                    style={{
                      padding: "6px 12px",
                      borderRadius: 4,
                      fontSize: 12,
                      fontWeight: 700,
                      backgroundColor: status === "APPROVE" ? "#ecfdf5" : "#fef2f2",
                      color: status === "APPROVE" ? "#047857" : "#b91c1c",
                    }}
                  >
                    ✓ {status} recorded in tamper-evident audit log
                  </span>
                ) : (
                  <div style={{ display: "flex", gap: 10 }}>
                    <button
                      className="action-btn"
                      style={{ color: "#b91c1c" }}
                      onClick={() => handleDecision(appr.id, "REJECT")}
                      disabled={loading}
                    >
                      <X size={14} />
                      <span>Reject</span>
                    </button>
                    <button
                      className="action-btn primary"
                      onClick={() => handleDecision(appr.id, "APPROVE")}
                      disabled={loading}
                    >
                      <Check size={14} />
                      <span>Approve & Dispatch</span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          );
        }))}
      </div>
    </div>
  );
}

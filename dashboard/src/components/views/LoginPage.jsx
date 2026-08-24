import React, { useState } from "react";
import { useAuth } from "../../context/AuthContext";
import "./LoginPage.css";

const INDUSTRY_TYPES = [
  { value: "steel",          label: "⚙️  Steel & Metals" },
  { value: "oil_gas",        label: "🛢️  Oil & Gas" },
  { value: "chemical",       label: "⚗️  Chemical" },
  { value: "mining",         label: "⛏️  Mining" },
  { value: "pharmaceutical", label: "💊  Pharmaceutical" },
  { value: "general",        label: "🏭  General Manufacturing" },
];

export default function LoginPage() {
  const { login } = useAuth();
  const [form, setForm] = useState({
    industryName: "",
    industryType: "",
    adminName: "",
    adminEmail: "",
    accessCode: "",
  });
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const validate = () => {
    const e = {};
    if (!form.industryName.trim()) e.industryName = "Industry name is required";
    if (!form.industryType) e.industryType = "Select an industry type";
    if (!form.adminName.trim()) e.adminName = "Your name is required";
    if (!form.adminEmail.trim() || !form.adminEmail.includes("@"))
      e.adminEmail = "Valid email required";
    if (!form.accessCode.trim()) e.accessCode = "Access code required";
    return e;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const e2 = validate();
    if (Object.keys(e2).length) { setErrors(e2); return; }
    setLoading(true);
    // Simulate brief auth delay for UX feel
    await new Promise((r) => setTimeout(r, 900));
    login(form.adminEmail.trim(), form.accessCode.trim());
  };

  return (
    <div className="login-root">
      {/* Animated background mesh */}
      <div className="login-bg">
        <div className="login-orb login-orb-1" />
        <div className="login-orb login-orb-2" />
        <div className="login-orb login-orb-3" />
      </div>

      <div className="login-card">
        {/* Brand header */}
        <div className="login-brand">
          <div className="login-logo">
            <svg viewBox="0 0 40 40" fill="none">
              <polygon points="20,3 37,32 3,32" fill="none" stroke="#f97316" strokeWidth="2.5" />
              <circle cx="20" cy="22" r="4" fill="#f97316" />
              <line x1="20" y1="12" x2="20" y2="18" stroke="#f97316" strokeWidth="2" />
            </svg>
          </div>
          <div>
            <h1 className="login-title">CausalCut</h1>
            <p className="login-subtitle">Industrial Safety Intelligence Platform</p>
          </div>
        </div>

        <div className="login-divider" />

        <p className="login-tagline">
          Register your industry to begin configuring your safety digital twin.
        </p>

        <form className="login-form" onSubmit={handleSubmit} noValidate>
          {/* Industry Name */}
          <div className="lf-group">
            <label className="lf-label">Industry / Company Name</label>
            <input
              id="login-industry-name"
              className={`lf-input ${errors.industryName ? "lf-input-error" : ""}`}
              placeholder="e.g. Steelforge Industries Ltd."
              value={form.industryName}
              onChange={(e) => set("industryName", e.target.value)}
              autoFocus
            />
            {errors.industryName && <span className="lf-error">{errors.industryName}</span>}
          </div>

          {/* Industry Type */}
          <div className="lf-group">
            <label className="lf-label">Industry Type</label>
            <div className="lf-industry-grid">
              {INDUSTRY_TYPES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  id={`login-industry-${t.value}`}
                  className={`lf-industry-chip ${form.industryType === t.value ? "lf-industry-chip-active" : ""}`}
                  onClick={() => set("industryType", t.value)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            {errors.industryType && <span className="lf-error">{errors.industryType}</span>}
          </div>

          {/* Two-column row */}
          <div className="lf-row">
            <div className="lf-group">
              <label className="lf-label">Your Name</label>
              <input
                id="login-admin-name"
                className={`lf-input ${errors.adminName ? "lf-input-error" : ""}`}
                placeholder="Full name"
                value={form.adminName}
                onChange={(e) => set("adminName", e.target.value)}
              />
              {errors.adminName && <span className="lf-error">{errors.adminName}</span>}
            </div>
            <div className="lf-group">
              <label className="lf-label">Work Email</label>
              <input
                id="login-admin-email"
                type="email"
                className={`lf-input ${errors.adminEmail ? "lf-input-error" : ""}`}
                placeholder="you@company.com"
                value={form.adminEmail}
                onChange={(e) => set("adminEmail", e.target.value)}
              />
              {errors.adminEmail && <span className="lf-error">{errors.adminEmail}</span>}
            </div>
          </div>

          {/* Access code */}
          <div className="lf-group">
            <label className="lf-label">Access Code</label>
            <input
              id="login-access-code"
              type="password"
              className={`lf-input ${errors.accessCode ? "lf-input-error" : ""}`}
              placeholder="Enter your access code"
              value={form.accessCode}
              onChange={(e) => set("accessCode", e.target.value)}
            />
            {errors.accessCode && <span className="lf-error">{errors.accessCode}</span>}
          </div>

          <button
            id="login-submit"
            type="submit"
            className="lf-submit"
            disabled={loading}
          >
            {loading ? (
              <span className="lf-spinner" />
            ) : (
              <>
                <span>Access Platform</span>
                <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                  <path fillRule="evenodd" d="M3 10a.75.75 0 01.75-.75h10.638L10.23 5.29a.75.75 0 111.04-1.08l5.5 5.25a.75.75 0 010 1.08l-5.5 5.25a.75.75 0 11-1.04-1.08l4.158-3.96H3.75A.75.75 0 013 10z" clipRule="evenodd" />
                </svg>
              </>
            )}
          </button>
        </form>

        <p className="login-footer">
          Demo platform · Any access code accepted · Session persists locally
        </p>
      </div>
    </div>
  );
}

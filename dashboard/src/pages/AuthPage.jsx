import React, { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import "./AuthPage.css";

const INDUSTRY_TYPES = [
  { value: "steel",    label: "⚙️  Integrated Steel Plant" },
  { value: "oil_gas",  label: "🛢️  Oil & Gas" },
  { value: "chemical", label: "⚗️  Chemical & Petrochemical" },
  { value: "mining",   label: "⛏️  Mining & Metallurgy" },
  { value: "pharma",   label: "💊  Pharmaceutical" },
  { value: "general",  label: "🏭  General Manufacturing" },
];

const ROLES = [
  { value: "admin",          label: "Lead Safety Manager" },
  { value: "safety_manager", label: "Safety Manager" },
  { value: "shift_officer",  label: "Senior Shift Officer" },
  { value: "operator",       label: "Reliability & Systems Engineer" },
];

export default function AuthPage() {
  const { session, login, signup, loading } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState(searchParams.get("tab") === "register" ? "register" : "login");

  // Redirect if already logged in
  useEffect(() => {
    if (!loading && session) navigate("/factories", { replace: true });
  }, [session, loading, navigate]);

  // Login form state
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);

  // Register form state
  const [regForm, setRegForm] = useState({
    companyName: "",
    adminName: "",
    email: "",
    password: "",
    confirmPassword: "",
    industryType: "steel",
    role: "admin",
  });
  const [regError, setRegError] = useState("");
  const [regLoading, setRegLoading] = useState(false);

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoginError("");
    if (!loginForm.email || !loginForm.password) {
      setLoginError("Please enter email and password.");
      return;
    }
    setLoginLoading(true);
    try {
      await login(loginForm.email, loginForm.password);
      navigate("/factories", { replace: true });
    } catch (err) {
      setLoginError(err.message || "Login failed. Check your credentials.");
    } finally {
      setLoginLoading(false);
    }
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    setRegError("");
    if (!regForm.companyName.trim()) return setRegError("Company name is required.");
    if (!regForm.adminName.trim())   return setRegError("Your name is required.");
    if (!regForm.email.includes("@")) return setRegError("Valid email required.");
    if (regForm.password.length < 8) return setRegError("Password must be at least 8 characters.");
    if (regForm.password !== regForm.confirmPassword) return setRegError("Passwords don't match.");

    setRegLoading(true);
    try {
      await signup({
        email: regForm.email,
        password: regForm.password,
        displayName: regForm.adminName.trim(),
        industryName: regForm.companyName.trim(),
        industryType: regForm.industryType,
        role: regForm.role,
      });
      // After signup, go to onboarding to set up first factory
      navigate("/onboarding", { replace: true });
    } catch (err) {
      setRegError(err.message || "Registration failed. Try again.");
    } finally {
      setRegLoading(false);
    }
  };

  return (
    <div className="auth-page-root">
      {/* Animated background */}
      <div className="auth-page-bg">
        <div className="auth-orb auth-orb-1" />
        <div className="auth-orb auth-orb-2" />
        <div className="auth-orb auth-orb-3" />
        <div className="auth-grid" />
      </div>

      {/* Back to landing */}
      <a href="/" className="auth-back-link">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M10 13L5 8l5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        Back to Home
      </a>

      <div className="auth-dialog-wrap">
        {/* Brand */}
        <div className="auth-brand-row">
          <svg className="auth-logo-icon" width="28" height="28" viewBox="0 0 24 24" fill="none">
            <circle cx="6" cy="6" r="3" fill="#4A8CB5"/>
            <circle cx="18" cy="6" r="3" fill="#4A8CB5"/>
            <circle cx="12" cy="18" r="3" fill="#F26522"/>
            <line x1="6" y1="6" x2="18" y2="6" stroke="#4A8CB5" strokeWidth="1.5"/>
            <line x1="6" y1="6" x2="12" y2="18" stroke="#4A8CB5" strokeWidth="1.5"/>
            <line x1="18" y1="6" x2="12" y2="18" stroke="#F26522" strokeWidth="1.5" strokeDasharray="3 2"/>
          </svg>
          <span className="auth-brand-name">CAUSALCUT GATEWAY</span>
        </div>

        {/* Tabs */}
        <div className="auth-tabs-row">
          <button
            className={`auth-tab-btn ${activeTab === "login" ? "active" : ""}`}
            onClick={() => setActiveTab("login")}
            id="tab-login"
          >
            Sign In
          </button>
          <button
            className={`auth-tab-btn ${activeTab === "register" ? "active" : ""}`}
            onClick={() => setActiveTab("register")}
            id="tab-register"
          >
            Register Company
          </button>
        </div>

        {/* ─── LOGIN PANE ─────────────────────────────────────── */}
        {activeTab === "login" && (
          <div className="auth-pane-content">
            <div className="pane-headline">
              <h3 className="pane-title">Access Plant Safety Twin</h3>
              <p className="pane-subtitle">Enter your enterprise shift credentials.</p>
            </div>

            {loginError && <div className="auth-alert error">{loginError}</div>}

            <form className="auth-form" onSubmit={handleLogin} noValidate>
              <div className="form-group">
                <label className="form-label" htmlFor="login-email">Enterprise Work Email</label>
                <input
                  id="login-email"
                  type="email"
                  className="form-input"
                  placeholder="officer@steelworks.com"
                  value={loginForm.email}
                  onChange={(e) => setLoginForm((p) => ({ ...p, email: e.target.value }))}
                  autoFocus
                  autoComplete="username"
                  required
                />
              </div>

              <div className="form-group">
                <div className="form-label-row">
                  <label className="form-label" htmlFor="login-password">Shift Passcode</label>
                </div>
                <input
                  id="login-password"
                  type="password"
                  className="form-input"
                  placeholder="••••••••••••"
                  value={loginForm.password}
                  onChange={(e) => setLoginForm((p) => ({ ...p, password: e.target.value }))}
                  autoComplete="current-password"
                  required
                />
              </div>

              <button
                id="btn-submit-login"
                type="submit"
                className="btn-auth-submit"
                disabled={loginLoading}
              >
                {loginLoading ? (
                  <span className="auth-spinner" />
                ) : (
                  <>
                    <span>Authenticate Shift Session</span>
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <path d="M1 7H13M13 7L7 1M13 7L7 13" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </>
                )}
              </button>

              <button
                type="button"
                className="btn-auth-submit"
                style={{ marginTop: "10px", background: "rgba(74,140,181,0.15)", border: "1px solid rgba(74,140,181,0.3)", color: "#7dc5ea" }}
                onClick={async () => {
                  setLoginLoading(true);
                  await login("officer@steelforge.ai", "demo-pass");
                  navigate("/factories", { replace: true });
                }}
              >
                <span>⚡ Quick Demo Shift Access</span>
              </button>
            </form>

            <p className="auth-switch-hint">
              No account?{" "}
              <button className="auth-switch-link" onClick={() => setActiveTab("register")}>
                Register your company →
              </button>
            </p>
          </div>
        )}

        {/* ─── REGISTER PANE ───────────────────────────────────── */}
        {activeTab === "register" && (
          <div className="auth-pane-content">
            <div className="pane-headline">
              <h3 className="pane-title">Provision Plant Safety Twin</h3>
              <p className="pane-subtitle">Register your facility & provision the defensive hypergraph twin.</p>
            </div>

            {regError && <div className="auth-alert error">{regError}</div>}

            <form className="auth-form" onSubmit={handleRegister} noValidate>
              <div className="form-row">
                <div className="form-group flex-1">
                  <label className="form-label" htmlFor="reg-company">Company / Enterprise Name</label>
                  <input
                    id="reg-company"
                    type="text"
                    className="form-input"
                    placeholder="e.g. ArcelorMittal / JSW"
                    value={regForm.companyName}
                    onChange={(e) => setRegForm((p) => ({ ...p, companyName: e.target.value }))}
                    required
                  />
                </div>
                <div className="form-group flex-1">
                  <label className="form-label" htmlFor="reg-admin-name">Safety Officer Full Name</label>
                  <input
                    id="reg-admin-name"
                    type="text"
                    className="form-input"
                    placeholder="e.g. Rajesh Kumar"
                    value={regForm.adminName}
                    onChange={(e) => setRegForm((p) => ({ ...p, adminName: e.target.value }))}
                    required
                  />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="reg-industry">Plant Classification</label>
                <div className="industry-chip-grid">
                  {INDUSTRY_TYPES.map((t) => (
                    <button
                      key={t.value}
                      type="button"
                      className={`industry-chip ${regForm.industryType === t.value ? "active" : ""}`}
                      onClick={() => setRegForm((p) => ({ ...p, industryType: t.value }))}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="form-row">
                <div className="form-group flex-1">
                  <label className="form-label" htmlFor="reg-admin-email">Corporate Work Email</label>
                  <input
                    id="reg-admin-email"
                    type="email"
                    className="form-input"
                    placeholder="r.kumar@company.com"
                    value={regForm.email}
                    onChange={(e) => setRegForm((p) => ({ ...p, email: e.target.value }))}
                    autoComplete="username"
                    required
                  />
                </div>
                <div className="form-group flex-1">
                  <label className="form-label" htmlFor="reg-role">Designated Role</label>
                  <select
                    id="reg-role"
                    className="form-select"
                    value={regForm.role}
                    onChange={(e) => setRegForm((p) => ({ ...p, role: e.target.value }))}
                  >
                    {ROLES.map((r) => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="form-row">
                <div className="form-group flex-1">
                  <label className="form-label" htmlFor="reg-password">Master Security Token</label>
                  <input
                    id="reg-password"
                    type="password"
                    className="form-input"
                    placeholder="Minimum 8 characters"
                    value={regForm.password}
                    onChange={(e) => setRegForm((p) => ({ ...p, password: e.target.value }))}
                    autoComplete="new-password"
                    required
                  />
                </div>
                <div className="form-group flex-1">
                  <label className="form-label" htmlFor="reg-confirm">Confirm Token</label>
                  <input
                    id="reg-confirm"
                    type="password"
                    className="form-input"
                    placeholder="Repeat password"
                    value={regForm.confirmPassword}
                    onChange={(e) => setRegForm((p) => ({ ...p, confirmPassword: e.target.value }))}
                    autoComplete="new-password"
                    required
                  />
                </div>
              </div>

              <button
                id="btn-submit-register"
                type="submit"
                className="btn-auth-submit btn-register-submit"
                disabled={regLoading}
              >
                {regLoading ? (
                  <span className="auth-spinner" />
                ) : (
                  <>
                    <span>Initialize Safety Twin & Provision Org</span>
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <path d="M2 12L12 2M12 2H5M12 2V9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </>
                )}
              </button>
            </form>

            <p className="auth-switch-hint">
              Already have an account?{" "}
              <button className="auth-switch-link" onClick={() => setActiveTab("login")}>
                Sign in →
              </button>
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

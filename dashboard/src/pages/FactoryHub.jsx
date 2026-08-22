import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import "./FactoryHub.css";

const INDUSTRY_LABELS = {
  steel:    { icon: "⚙️",  label: "Steel Plant" },
  oil_gas:  { icon: "🛢️",  label: "Oil & Gas" },
  chemical: { icon: "⚗️",  label: "Chemical" },
  mining:   { icon: "⛏️",  label: "Mining" },
  pharma:   { icon: "💊",  label: "Pharmaceutical" },
  general:  { icon: "🏭",  label: "Manufacturing" },
};

const INDUSTRY_COLORS = {
  steel:    "#4A8CB5",
  oil_gas:  "#F26522",
  chemical: "#22C55E",
  mining:   "#a78bfa",
  pharma:   "#f472b6",
  general:  "#94a3b8",
};

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
  });
}

export default function FactoryHub() {
  const { session, userProfile, factories, loading, logout, refreshFactories } = useAuth();
  const navigate = useNavigate();

  // Protect route
  useEffect(() => {
    if (!loading && !session) navigate("/auth", { replace: true });
  }, [session, loading, navigate]);

  useEffect(() => {
    if (session) refreshFactories();
  }, [session]); // eslint-disable-line

  if (loading) {
    return (
      <div className="hub-loading">
        <div className="hub-loading-spinner" />
        <p>Loading your factories…</p>
      </div>
    );
  }

  const displayName = userProfile?.display_name || session?.user?.email?.split("@")[0] || "User";
  const companyName = userProfile?.industry_name || "Your Company";

  return (
    <div className="hub-root">
      {/* Ambient bg */}
      <div className="hub-bg">
        <div className="hub-orb hub-orb-1" />
        <div className="hub-orb hub-orb-2" />
        <div className="hub-grid" />
      </div>

      {/* Header */}
      <header className="hub-header">
        <div className="hub-brand">
          <svg className="hub-logo" width="24" height="24" viewBox="0 0 24 24" fill="none">
            <circle cx="6" cy="6" r="3" fill="#4A8CB5"/>
            <circle cx="18" cy="6" r="3" fill="#4A8CB5"/>
            <circle cx="12" cy="18" r="3" fill="#F26522"/>
            <line x1="6" y1="6" x2="18" y2="6" stroke="#4A8CB5" strokeWidth="1.5"/>
            <line x1="6" y1="6" x2="12" y2="18" stroke="#4A8CB5" strokeWidth="1.5"/>
            <line x1="18" y1="6" x2="12" y2="18" stroke="#F26522" strokeWidth="1.5" strokeDasharray="3 2"/>
          </svg>
          <span className="hub-brand-name">CAUSALCUT</span>
        </div>

        <div className="hub-user-row">
          <div className="hub-user-info">
            <span className="hub-user-name">{displayName}</span>
            <span className="hub-user-company">{companyName}</span>
          </div>
          <div className="hub-avatar">
            {displayName.charAt(0).toUpperCase()}
          </div>
          <button className="hub-logout-btn" onClick={logout} title="Sign out">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M6 14H3a1 1 0 01-1-1V3a1 1 0 011-1h3M11 11l3-3-3-3M14 8H6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
        </div>
      </header>

      {/* Main content */}
      <main className="hub-main">
        <div className="hub-page-header">
          <div>
            <h1 className="hub-title">Your Factories</h1>
            <p className="hub-subtitle">
              {factories.length === 0
                ? "No factories configured yet. Add your first factory to get started."
                : `${factories.length} facilit${factories.length === 1 ? "y" : "ies"} monitored`}
            </p>
          </div>
          <button
            id="btn-add-factory"
            className="hub-add-btn"
            onClick={() => navigate("/onboarding")}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
            </svg>
            Add Factory
          </button>
        </div>

        {/* Empty state */}
        {factories.length === 0 && (
          <div className="hub-empty">
            <div className="hub-empty-icon">🏭</div>
            <h3>No factories yet</h3>
            <p>Upload a factory blueprint and configure your safety digital twin.</p>
            <button
              className="hub-add-btn"
              onClick={() => navigate("/onboarding")}
              style={{ marginTop: "20px" }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
              </svg>
              Add First Factory
            </button>
          </div>
        )}

        {/* Factory grid */}
        {factories.length > 0 && (
          <div className="hub-grid-cards">
            {factories.map((factory) => {
              const ind = INDUSTRY_LABELS[factory.industry_type] || INDUSTRY_LABELS.general;
              const color = INDUSTRY_COLORS[factory.industry_type] || INDUSTRY_COLORS.general;
              const floorCount = factory.factory_floors?.[0]?.count ?? 0;

              return (
                <button
                  key={factory.id}
                  className="hub-factory-card"
                  id={`factory-card-${factory.id}`}
                  onClick={() => navigate(`/dashboard/${factory.id}`)}
                  style={{ "--accent": color }}
                >
                  <div className="hub-card-top">
                    <div className="hub-card-icon" style={{ background: `${color}20`, border: `1px solid ${color}40` }}>
                      <span>{ind.icon}</span>
                    </div>
                    <div className="hub-card-status">
                      <span className="hub-status-dot" />
                      LIVE
                    </div>
                  </div>

                  <div className="hub-card-body">
                    <h3 className="hub-card-name">{factory.name}</h3>
                    {factory.location && (
                      <p className="hub-card-location">
                        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                          <circle cx="6" cy="5" r="2.5" stroke="currentColor" strokeWidth="1.3"/>
                          <path d="M6 1C3.8 1 2 2.8 2 5c0 3 4 8 4 8s4-5 4-8c0-2.2-1.8-4-4-4z" stroke="currentColor" strokeWidth="1.3" fill="none"/>
                        </svg>
                        {factory.location}
                      </p>
                    )}
                    <p className="hub-card-type">{ind.label}</p>
                  </div>

                  <div className="hub-card-footer">
                    <div className="hub-card-stat">
                      <span className="hub-card-stat-num">{floorCount}</span>
                      <span className="hub-card-stat-label">Floors</span>
                    </div>
                    <div className="hub-card-stat">
                      <span className="hub-card-stat-num hub-stat-live" style={{ color }}>●</span>
                      <span className="hub-card-stat-label">Active</span>
                    </div>
                    <div className="hub-card-stat">
                      <span className="hub-card-stat-label">{formatDate(factory.created_at)}</span>
                    </div>
                    <div className="hub-card-arrow" style={{ color }}>
                      <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                        <path d="M4 9h10M10 5l4 4-4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    </div>
                  </div>
                </button>
              );
            })}

            {/* Add factory card */}
            <button
              className="hub-factory-card hub-add-card"
              onClick={() => navigate("/onboarding")}
              id="btn-add-factory-card"
            >
              <div className="hub-add-card-inner">
                <div className="hub-add-card-icon">
                  <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                    <path d="M14 6v16M6 14h16" stroke="#4A8CB5" strokeWidth="2" strokeLinecap="round"/>
                  </svg>
                </div>
                <span className="hub-add-card-label">Add Factory</span>
                <span className="hub-add-card-sub">Upload blueprint & configure safety twin</span>
              </div>
            </button>
          </div>
        )}
      </main>
    </div>
  );
}

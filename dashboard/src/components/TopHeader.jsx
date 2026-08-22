import React, { useState, useEffect } from "react";
import { Bell, LogOut, ChevronLeft } from "lucide-react";

export default function TopHeader({ facility = "Steel Plant — Coke Oven Facility", isMonitoring = true, onLogout, onBackToHub }) {
  const [currentTime, setCurrentTime] = useState("");

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      // Format as "21 Aug 2026 · 00:09 IST"
      const datePart = now.toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      });
      const timePart = now.toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
      setCurrentTime(`${datePart} · ${timePart} IST`);
    };

    updateTime();
    const interval = setInterval(updateTime, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="top-header">
      <div className="facility-badge-group">
        {onBackToHub && (
          <button
            onClick={onBackToHub}
            title="Back to My Factories"
            style={{
              background: "rgba(255,255,255,0.06)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: "6px",
              padding: "4px 8px",
              color: "rgba(255,255,255,0.5)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "2px",
              fontSize: "11px",
              fontWeight: 600,
              letterSpacing: "0.04em",
              marginRight: "8px",
              transition: "all 0.2s",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = "rgba(255,255,255,0.8)"; e.currentTarget.style.borderColor = "rgba(255,255,255,0.2)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = "rgba(255,255,255,0.5)"; e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)"; }}
          >
            <ChevronLeft size={12} /> MY FACTORIES
          </button>
        )}
        <span className="facility-label">ACTIVE FACILITY</span>
        <span className="facility-name">{facility}</span>
      </div>

      <div className="header-right">
        <div className="datetime-pill">{currentTime || "21 Aug 2026 · 00:09 IST"}</div>
        <div className="monitoring-indicator">
          <span className="pulse-dot" />
          <span>{isMonitoring ? "MONITORING" : "STANDBY"}</span>
        </div>
        <button className="icon-button" title="Notifications">
          <Bell size={16} />
        </button>
        {onLogout && (
          <button className="icon-button logout-btn" title="Log Out" onClick={onLogout} style={{ color: '#ef4444' }}>
            <LogOut size={16} />
          </button>
        )}
      </div>
    </header>
  );
}

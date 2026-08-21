import React, { useState, useEffect } from "react";
import { Bell, RefreshCw } from "lucide-react";

export default function TopHeader({ facility = "Steel Plant — Coke Oven Facility", isMonitoring = true }) {
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
      </div>
    </header>
  );
}

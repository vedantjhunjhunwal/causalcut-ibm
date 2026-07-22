import { useEffect, useState } from "react";
import { api } from "../api";

export default function ModelStatus() {
  const [models, setModels] = useState(null);

  useEffect(() => {
    let alive = true;
    const fetchStatus = async () => {
      try {
        const data = await api.modelStatus();
        if (alive) setModels(data);
      } catch (e) {
        // ignore — backend may not be running
      }
    };
    fetchStatus();
    const t = setInterval(fetchStatus, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (!models) return (
    <div className="panel">
      <div className="panel-title">Model Status</div>
      <div className="faint" style={{ fontSize: 12 }}>Loading…</div>
    </div>
  );

  // status_all() returns { gas: {available, artifact_path, degraded_reason, ...}, ... }
  const entries = Object.entries(models).filter(([k]) => k !== "execution_mode");

  return (
    <div className="panel">
      <div className="panel-title">Model Status</div>
      <div className="model-list">
        {entries.map(([name, info]) => {
          const avail = info.available === true ? "real"
            : info.degraded_reason ? "degraded" : "unavailable";
          const dotCls = avail === "real" ? "green"
            : avail === "degraded" ? "amber" : "red";
          return (
            <div key={name} className="model-row">
              <div className={`model-dot ${dotCls}`} />
              <div className="model-name">{name}</div>
              <div className="model-info">
                {avail === "real" ? "ready" : info.degraded_reason || "unavailable"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

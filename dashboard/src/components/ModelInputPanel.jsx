import React, { useState, useRef, useEffect } from "react";
import { API } from "../api";
import { Layers, Cpu, Eye, Navigation, CheckCircle, ChevronDown, ChevronUp, Upload } from "lucide-react";

const HYD_SENSORS = [
  ["PS1", "bar", "Pressure 1"],
  ["PS2", "bar", "Pressure 2"],
  ["PS3", "bar", "Pressure 3"],
  ["PS4", "bar", "Pressure 4"],
  ["PS5", "bar", "Pressure 5"],
  ["PS6", "bar", "Pressure 6"],
  ["EPS1", "W", "Motor power"],
  ["FS1", "l/min", "Volume flow 1"],
  ["FS2", "l/min", "Volume flow 2"],
  ["TS1", "°C", "Temperature 1"],
  ["TS2", "°C", "Temperature 2"],
  ["TS3", "°C", "Temperature 3"],
  ["TS4", "°C", "Temperature 4"],
  ["VS1", "mm/s", "Vibration"],
  ["CE", "%", "Cooling efficiency"],
  ["CP", "kW", "Cooling power"],
  ["SE", "%", "Efficiency factor"],
];

export default function ModelInputPanel({ scenario, setScenario }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("hydraulic");
  const [zoneId, setZoneId] = useState("zone-1");
  const [hydData, setHydData] = useState({});
  const [jsonText, setJsonText] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [banner, setBanner] = useState(null);

  const [imageSrc, setImageSrc] = useState(null);
  const canvasRef = useRef(null);
  const imageRef = useRef(null);

  const zones = scenario?.zones || [];

  const handleImageUpload = (e) => {
    const file = e.target.files[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        setImageSrc(event.target.result);
        setTestResult(null); // Clear previous results
      };
      reader.readAsDataURL(file);
    }
  };

  useEffect(() => {
    if (imageSrc && canvasRef.current && imageRef.current) {
      const ctx = canvasRef.current.getContext("2d");
      const img = imageRef.current;
      img.onload = () => {
        canvasRef.current.width = img.width;
        canvasRef.current.height = img.height;
        ctx.clearRect(0, 0, img.width, img.height);
        ctx.drawImage(img, 0, 0);

        if (testResult && testResult.prediction) {
           let detections = testResult.prediction.detections || testResult.prediction;
           if (!Array.isArray(detections) && testResult.prediction.boxes) detections = testResult.prediction.boxes;
           if (Array.isArray(detections)) {
             detections.forEach(det => {
               const box = det.bbox_xyxy || det.box || [det.x1, det.y1, det.x2, det.y2];
               if (box && box.length === 4) {
                 ctx.strokeStyle = (det.class_name && (det.class_name.includes("no_") || det.class_name === "person")) ? (det.class_name === "person" ? "#3b82f6" : "#ef4444") : "#10b981";
                 ctx.lineWidth = 3;
                 ctx.strokeRect(box[0], box[1], box[2] - box[0], box[3] - box[1]);
                 ctx.fillStyle = ctx.strokeStyle;
                 ctx.font = "16px sans-serif";
                 const label = `${det.class_name || det.class || "object"} ${det.track_id ? "ID:" + det.track_id : ""}`;
                 ctx.fillText(label, box[0], box[1] > 20 ? box[1] - 5 : box[1] + 15);
               }
             });
           }
        }
      };
      if (img.complete) img.onload();
    }
  }, [imageSrc, testResult, tab]);

  const handleTestInference = async () => {
    setTesting(true);
    setTestResult(null);
    setBanner(null);
    try {
      let payload = {};
      let endpoint = `${API}/models/${tab}/predict`;

      if (tab === "hydraulic") {
        if (jsonText.trim()) {
          try {
            payload = JSON.parse(jsonText);
          } catch (e) {
            setBanner({ ok: false, msg: "Invalid JSON in sensor data field." });
            setTesting(false);
            return;
          }
        } else {
          payload = { sensor_data: hydData };
        }
      } else if (tab === "vision") {
        endpoint = `${API}/models/vision/detect`;
        if (!imageSrc) {
            setBanner({ ok: false, msg: "Please upload an image first." });
            setTesting(false);
            return;
        }
        payload = { image_ref: { format: "base64", data: imageSrc.split(",")[1] } };
      } else if (tab === "tracking") {
        if (!imageSrc) {
            setBanner({ ok: false, msg: "Please upload an image first to run vision + tracking pipeline." });
            setTesting(false);
            return;
        }
        const visRes = await fetch(`${API}/models/vision/detect`, {
           method: "POST",
           headers: { "Content-Type": "application/json" },
           body: JSON.stringify({ image_ref: { format: "base64", data: imageSrc.split(",")[1] }, zone_id: zoneId }),
        });
        const visData = await visRes.json();
        
        let detections = [];
        if (visData && visData.prediction) {
            detections = visData.prediction.detections || visData.prediction;
        }

        endpoint = `${API}/models/tracking/update`;
        payload = { detections: detections };
      }

      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, zone_id: zoneId }),
      });
      const data = await res.json();
      
      // Filter out detections below 0.5 confidence
      if (data && data.prediction) {
          let detList = data.prediction.detections || data.prediction;
          if (Array.isArray(detList)) {
              const filtered = detList.filter(d => (typeof d.confidence !== 'number' || d.confidence >= 0.5));
              if (data.prediction.detections) {
                  data.prediction.detections = filtered;
              } else {
                  data.prediction = filtered;
              }
          }
      }
      
      setTestResult(data);
    } catch (e) {
      setBanner({ ok: false, msg: `Inference failed: ${e.message}` });
    } finally {
      setTesting(false);
    }
  };

  const handleAddToScenario = () => {
    if (tab === "hydraulic") {
      let parsed = hydData;
      if (jsonText.trim()) {
        try {
          parsed = JSON.parse(jsonText);
        } catch (e) {
          setBanner({ ok: false, msg: "Invalid JSON." });
          return;
        }
      }
      const newReading = {
        zone_id: zoneId || "zone-1",
        sensor_data: parsed.sensor_data || parsed,
        offset_seconds: 0,
      };
      setScenario((prev) => ({
        ...prev,
        hydraulic_readings: [...(prev.hydraulic_readings || []), newReading],
      }));
      setBanner({ ok: true, msg: "Added hydraulic reading to scenario pipeline!" });
    }
  };

  return (
    <div className="panel-box" style={{ padding: 16 }}>
      <div
        className="panel-header-row"
        style={{ cursor: "pointer", marginBottom: open ? 12 : 0 }}
        onClick={() => setOpen(!open)}
      >
        <div>
          <span className="panel-title-text">RAW MODEL INPUTS & TESTING</span>
          <span className="panel-meta-text" style={{ marginLeft: 10 }}>
            OPTIONAL ARRAYS & ML TEST HARNESS
          </span>
        </div>
        <button className="icon-button" style={{ width: 28, height: 28 }}>
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </div>

      {open && (
        <div style={{ marginTop: 12 }}>
          {/* Tabs */}
          <div className="filter-pills-row" style={{ marginBottom: 12 }}>
            <button
              className={`filter-pill ${tab === "hydraulic" ? "active" : ""}`}
              onClick={() => setTab("hydraulic")}
            >
              Hydraulic Condition
            </button>
            <button
              className={`filter-pill ${tab === "vision" ? "active" : ""}`}
              onClick={() => setTab("vision")}
            >
              YOLOv8 Vision
            </button>
            <button
              className={`filter-pill ${tab === "tracking" ? "active" : ""}`}
              onClick={() => setTab("tracking")}
            >
              ByteTrack
            </button>
          </div>

          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", display: "block", marginBottom: 4 }}>
              Target Zone
            </label>
            <select
              style={{ width: "100%", padding: "6px 10px", fontSize: 12, borderRadius: 4, border: "1px solid #cbd5e1" }}
              value={zoneId}
              onChange={(e) => setZoneId(e.target.value)}
            >
              {zones.length > 0 ? (
                zones.map((z) => (
                  <option key={z.zone_id} value={z.zone_id}>
                    {z.name || z.zone_id} ({z.zone_id})
                  </option>
                ))
              ) : (
                <option value="zone-1">Zone 1 (Coke Oven)</option>
              )}
            </select>
          </div>

          {tab === "hydraulic" && (
            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", display: "block", marginBottom: 4 }}>
                17 Hydraulic Sensors (Optional Array or Paste JSON)
              </label>
              <textarea
                rows={3}
                placeholder='Paste JSON: {"PS1": [155.6], "PS2": [155.8], "EPS1": [2400], ...}'
                style={{ width: "100%", padding: "6px 10px", fontSize: 11, fontFamily: "var(--font-mono)", borderRadius: 4, border: "1px solid #cbd5e1" }}
                value={jsonText}
                onChange={(e) => setJsonText(e.target.value)}
              />
            </div>
          )}

          {(tab === "vision" || tab === "tracking") && (
            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", display: "block", marginBottom: 4 }}>
                Upload Image for Inference
              </label>
              <input type="file" accept="image/*" onChange={handleImageUpload} style={{ fontSize: 12, marginBottom: 12 }} />
              
              {imageSrc && (
                <div style={{ position: "relative", width: "100%", maxWidth: 640, margin: "10px 0" }}>
                  <img
                    ref={imageRef}
                    src={imageSrc}
                    alt="Uploaded"
                    style={{ display: "none" }}
                  />
                  <canvas 
                    ref={canvasRef} 
                    style={{ width: "100%", height: "auto", border: "1px solid #cbd5e1", borderRadius: 4 }}
                  />
                </div>
              )}
            </div>
          )}

          {banner && (
            <div
              style={{
                marginTop: 10,
                padding: "8px 12px",
                borderRadius: 4,
                fontSize: 11.5,
                fontWeight: 600,
                backgroundColor: banner.ok ? "#ecfdf5" : "#fef2f2",
                color: banner.ok ? "#047857" : "#b91c1c",
                border: `1px solid ${banner.ok ? "#a7f3d0" : "#fecaca"}`,
              }}
            >
              {banner.msg}
            </div>
          )}

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button className="action-btn" onClick={handleTestInference} disabled={testing}>
              {testing ? "Testing…" : "Test Model Inference"}
            </button>
            <button className="action-btn primary" onClick={handleAddToScenario}>
              Add to Scenario
            </button>
          </div>

          {testResult && (
            <div style={{ marginTop: 12, padding: 10, backgroundColor: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 4 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#0f172a", marginBottom: 4 }}>
                Inference Result: {testResult.model_name} (Mode: {testResult.inference_mode})
              </div>
              <pre style={{ margin: 0, fontSize: 10.5, fontFamily: "var(--font-mono)", color: "#334155", maxHeight: 120, overflow: "auto" }}>
                {JSON.stringify(testResult, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}


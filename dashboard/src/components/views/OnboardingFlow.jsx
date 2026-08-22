import React, { useState, useRef, useCallback } from "react";
import { useAuth } from "../../context/AuthContext";
import BlueprintCanvas from "../BlueprintCanvas";
import "./OnboardingFlow.css";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api/v1";

const STEPS = [
  { id: "factory",   label: "Factory Details" },
  { id: "upload",    label: "Blueprint Upload" },
  { id: "analysis",  label: "Zone Analysis" },
];

const INDUSTRY_HAZARD_DEFAULTS = {
  steel:          { gas_threshold: 150, hazard: "flammable"    },
  oil_gas:        { gas_threshold: 100, hazard: "flammable"    },
  chemical:       { gas_threshold: 100, hazard: "toxic"        },
  mining:         { gas_threshold: 120, hazard: "toxic"        },
  pharmaceutical: { gas_threshold: 200, hazard: "general"      },
  general:        { gas_threshold: 200, hazard: "general"      },
};

export default function OnboardingFlow() {
  const { session, setFactory } = useAuth();
  const [step, setStep] = useState(0);

  // Step 1 — Factory details
  const [factoryForm, setFactoryForm] = useState({
    name: "",
    location: "",
    floor: "Ground Floor",
  });
  const [factoryErrors, setFactoryErrors] = useState({});

  // Step 2 — Blueprint upload
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [imageB64, setImageB64] = useState(null);
  const [imageMime, setImageMime] = useState("image/png");
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef();

  // Step 3 — Analysis
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);   // { zones, zone_adjacency, sensors }
  const [confirming, setConfirming] = useState(false);

  // ------------------------------------------------------------------ //
  // Step 1 helpers
  // ------------------------------------------------------------------ //
  const setF = (k, v) => setFactoryForm((p) => ({ ...p, [k]: v }));

  const validateFactory = () => {
    const e = {};
    if (!factoryForm.name.trim()) e.name = "Factory name is required";
    if (!factoryForm.location.trim()) e.location = "Location is required";
    return e;
  };

  const goToUpload = () => {
    const e = validateFactory();
    if (Object.keys(e).length) { setFactoryErrors(e); return; }
    setFactoryErrors({});
    setStep(1);
  };

  // ------------------------------------------------------------------ //
  // Step 2 helpers — file handling
  // ------------------------------------------------------------------ //
  const loadFile = (file) => {
    if (!file) return;
    setImageFile(file);
    setImageMime(file.type || "image/png");

    const reader = new FileReader();
    reader.onload = (ev) => {
      setImagePreview(ev.target.result);             // data URL for <img>
      const b64 = ev.target.result.split(",")[1];    // strip data:…;base64,
      setImageB64(b64);
    };
    reader.readAsDataURL(file);
  };

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file && (file.type.startsWith("image/") || file.type === "application/pdf")) {
      loadFile(file);
    }
  }, []);

  const onFileChange = (e) => loadFile(e.target.files?.[0]);

  // ------------------------------------------------------------------ //
  // Step 3 — call backend
  // ------------------------------------------------------------------ //
  const analyzeBlueprint = async () => {
    if (!imageB64) return;
    setAnalyzing(true);
    setAnalysisError(null);
    setStep(2);

    try {
      const res = await fetch(`${API_BASE}/blueprints/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_b64: imageB64,
          image_mime: imageMime,
          industry_type: session.industryType,
          factory_name: factoryForm.name,
          floor_label: factoryForm.floor,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Analysis failed (HTTP ${res.status})`);
      }

      const data = await res.json();
      setAnalysisResult(data);
    } catch (err) {
      setAnalysisError(err.message);
    } finally {
      setAnalyzing(false);
    }
  };

  // Called when the BlueprintCanvas emits a confirmed layout
  const handleCanvasConfirm = async (layout) => {
    setConfirming(true);
    const factory = {
      name: factoryForm.name,
      location: factoryForm.location,
      floor: factoryForm.floor,
      industryType: session.industryType,
      blueprintDataUrl: imagePreview,
      zones: layout.zones,
      zone_adjacency: layout.zone_adjacency,
      sensors: layout.sensors,
      createdAt: Date.now(),
    };
    // Small artificial delay so "Saving…" state is visible
    await new Promise((r) => setTimeout(r, 600));
    setFactory(factory);
    setConfirming(false);
    // App.jsx auth gate will automatically switch to the main dashboard
  };

  // ------------------------------------------------------------------ //
  // Render
  // ------------------------------------------------------------------ //
  return (
    <div className="ob-root">
      {/* Background */}
      <div className="ob-bg">
        <div className="ob-orb ob-orb-1" />
        <div className="ob-orb ob-orb-2" />
      </div>

      {/* Progress bar */}
      <div className="ob-progress-bar">
        {STEPS.map((s, i) => (
          <React.Fragment key={s.id}>
            <div className={`ob-step ${i < step ? "ob-step-done" : i === step ? "ob-step-active" : ""}`}>
              <div className="ob-step-dot">
                {i < step ? (
                  <svg viewBox="0 0 16 16" fill="currentColor" width="12" height="12">
                    <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z"/>
                  </svg>
                ) : (
                  <span>{i + 1}</span>
                )}
              </div>
              <span className="ob-step-label">{s.label}</span>
            </div>
            {i < STEPS.length - 1 && <div className={`ob-step-line ${i < step ? "ob-step-line-done" : ""}`} />}
          </React.Fragment>
        ))}
      </div>

      {/* Card */}
      <div className="ob-card">

        {/* =============== STEP 1: Factory Details =============== */}
        {step === 0 && (
          <div className="ob-pane" key="factory">
            <h2 className="ob-pane-title">Your Factory Details</h2>
            <p className="ob-pane-sub">
              Tell us about the facility you're configuring for{" "}
              <strong>{session.industryName}</strong>.
            </p>

            <div className="ob-form">
              <div className="ob-field">
                <label className="ob-label">Factory / Facility Name</label>
                <input
                  id="ob-factory-name"
                  className={`ob-input ${factoryErrors.name ? "ob-input-error" : ""}`}
                  placeholder="e.g. Coke Oven Battery Unit 3"
                  value={factoryForm.name}
                  onChange={(e) => setF("name", e.target.value)}
                  autoFocus
                />
                {factoryErrors.name && <span className="ob-error">{factoryErrors.name}</span>}
              </div>

              <div className="ob-field">
                <label className="ob-label">Location / Site</label>
                <input
                  id="ob-factory-location"
                  className={`ob-input ${factoryErrors.location ? "ob-input-error" : ""}`}
                  placeholder="e.g. Hyderabad, Telangana"
                  value={factoryForm.location}
                  onChange={(e) => setF("location", e.target.value)}
                />
                {factoryErrors.location && <span className="ob-error">{factoryErrors.location}</span>}
              </div>

              <div className="ob-field">
                <label className="ob-label">Floor / Level</label>
                <select
                  id="ob-factory-floor"
                  className="ob-input"
                  value={factoryForm.floor}
                  onChange={(e) => setF("floor", e.target.value)}
                >
                  {["Ground Floor", "Level 1", "Level 2", "Level 3", "Basement", "Roof Level"].map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="ob-actions">
              <button id="ob-next-upload" className="ob-btn-primary" onClick={goToUpload}>
                Next: Upload Blueprint →
              </button>
            </div>
          </div>
        )}

        {/* =============== STEP 2: Upload =============== */}
        {step === 1 && (
          <div className="ob-pane" key="upload">
            <h2 className="ob-pane-title">Upload Factory Blueprint</h2>
            <p className="ob-pane-sub">
              Upload a floor plan for <strong>{factoryForm.name}</strong>. Gemini will extract zones automatically — you can refine them after.
            </p>

            <div
              id="ob-dropzone"
              className={`ob-dropzone ${dragOver ? "ob-dropzone-over" : ""} ${imageFile ? "ob-dropzone-filled" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => !imageFile && fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/jpg,image/webp"
                style={{ display: "none" }}
                onChange={onFileChange}
              />

              {imageFile ? (
                <div className="ob-preview-wrap">
                  <img src={imagePreview} alt="Blueprint preview" className="ob-preview-img" />
                  <div className="ob-preview-overlay">
                    <button
                      id="ob-replace-file"
                      className="ob-replace-btn"
                      onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click(); }}
                    >
                      Replace Image
                    </button>
                  </div>
                </div>
              ) : (
                <div className="ob-drop-prompt">
                  <div className="ob-drop-icon">
                    <svg viewBox="0 0 48 48" fill="none">
                      <rect x="6" y="6" width="36" height="36" rx="4" stroke="currentColor" strokeWidth="2" strokeDasharray="4 3"/>
                      <path d="M24 18v12M18 24l6-6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </div>
                  <p className="ob-drop-title">Drop your blueprint here</p>
                  <p className="ob-drop-sub">PNG, JPEG, or WebP · or <span className="ob-drop-link">browse files</span></p>
                </div>
              )}
            </div>

            <div className="ob-actions ob-actions-row">
              <button className="ob-btn-ghost" onClick={() => setStep(0)}>← Back</button>
              <button
                id="ob-analyze-btn"
                className="ob-btn-primary"
                disabled={!imageFile}
                onClick={analyzeBlueprint}
              >
                Analyze with Gemini →
              </button>
            </div>
          </div>
        )}

        {/* =============== STEP 3: Analysis =============== */}
        {step === 2 && (
          <div className="ob-pane ob-pane-analysis" key="analysis">
            <h2 className="ob-pane-title">Zone Analysis</h2>
            <p className="ob-pane-sub">
              {analyzing
                ? "Gemini is reading your blueprint…"
                : analysisError
                ? "Analysis failed. You can draw zones manually below."
                : "Zones detected. Review and adjust, then confirm to launch your Safety Twin."}
            </p>

            {analyzing && (
              <div className="ob-analyzing">
                <div className="ob-analyze-spinner" />
                <div className="ob-analyze-steps">
                  {["Uploading blueprint", "Running Gemini 2.5 Flash Lite", "Extracting zones & sensors", "Validating layout"].map((s, i) => (
                    <div key={s} className="ob-analyze-step" style={{ animationDelay: `${i * 0.4}s` }}>
                      <div className="ob-analyze-dot" />
                      <span>{s}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {analysisError && !analyzing && (
              <div className="ob-error-banner">
                <strong>⚠ Analysis error:</strong> {analysisError}
                <br /><small>You can draw zones manually on the canvas below.</small>
              </div>
            )}

            {!analyzing && (
              <BlueprintCanvas
                imageDataUrl={imagePreview}
                initialZones={analysisResult?.zones ?? []}
                initialAdjacency={analysisResult?.zone_adjacency ?? []}
                initialSensors={analysisResult?.sensors ?? []}
                onConfirm={handleCanvasConfirm}
                confirming={confirming}
              />
            )}

            {!analyzing && (
              <div className="ob-actions ob-actions-row" style={{ marginTop: 12 }}>
                <button className="ob-btn-ghost" onClick={() => { setStep(1); setAnalysisResult(null); setAnalysisError(null); }}>
                  ← Re-upload
                </button>
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
}

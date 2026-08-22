import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./context/AuthContext";

import LandingPage    from "./pages/LandingPage";
import AuthPage       from "./pages/AuthPage";
import FactoryHub     from "./pages/FactoryHub";
import OnboardingFlow from "./components/views/OnboardingFlow";
import App            from "./App";

/** Redirect to /auth if the user is not logged in */
function Protected({ children }) {
  const { session, loading } = useAuth();
  if (loading) return <LoadingScreen />;
  if (!session) return <Navigate to="/auth" replace />;
  return children;
}

function LoadingScreen() {
  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "#0a0c0f",
      fontFamily: "Inter, sans-serif",
      color: "rgba(255,255,255,0.5)",
      flexDirection: "column",
      gap: "16px",
    }}>
      <div style={{
        width: 40, height: 40,
        border: "3px solid rgba(74,140,181,0.2)",
        borderTopColor: "#4A8CB5",
        borderRadius: "50%",
        animation: "spin 0.8s linear infinite",
      }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <p style={{ margin: 0 }}>Authenticating…</p>
    </div>
  );
}

export default function AppRouter() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/"     element={<LandingPage />} />
      <Route path="/auth" element={<AuthPage />} />

      {/* Protected routes */}
      <Route path="/factories" element={
        <Protected><FactoryHub /></Protected>
      } />
      <Route path="/onboarding" element={
        <Protected><OnboardingFlow /></Protected>
      } />
      <Route path="/dashboard/:factoryId" element={
        <Protected><App /></Protected>
      } />

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

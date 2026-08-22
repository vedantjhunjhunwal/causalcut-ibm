import React, { createContext, useContext, useState, useEffect } from "react";

const AuthContext = createContext(null);

const STORAGE_KEY = "causalcut_session";

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored ? JSON.parse(stored) : null;
    } catch {
      return null;
    }
  });

  // Persist any session change
  useEffect(() => {
    if (session) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [session]);

  const login = ({ industryName, industryType, adminName, adminEmail }) => {
    setSession({
      industryName,
      industryType,
      adminName,
      adminEmail,
      factory: null,          // set after blueprint onboarding
      loginAt: Date.now(),
    });
  };

  const setFactory = (factory) => {
    setSession((prev) => ({ ...prev, factory }));
  };

  const logout = () => setSession(null);

  return (
    <AuthContext.Provider value={{ session, login, setFactory, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}

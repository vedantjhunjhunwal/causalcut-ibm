// @refresh reset
import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { supabase } from "../lib/supabase";

const AuthContext = createContext(null);


export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);         // Supabase auth session
  const [userProfile, setUserProfile] = useState(null); // user_profiles row
  const [factories, setFactories] = useState([]);        // factories[] for this user
  const [loading, setLoading] = useState(true);          // resolving initial session

  // ── Fetch the user's profile + factories from Supabase or LocalStorage ──
  const loadUserData = useCallback(async (userId) => {
    try {
      const [profileRes, factoriesRes] = await Promise.all([
        supabase
          .from("user_profiles")
          .select("*")
          .eq("auth_id", userId)
          .single(),
        supabase
          .from("factories")
          .select("*, factory_floors(count)")
          .eq("owner_id", userId)
          .order("created_at", { ascending: false }),
      ]);

      if (profileRes.data) setUserProfile(profileRes.data);
      if (factoriesRes.data?.length) {
        setFactories(factoriesRes.data);
        return;
      }
    } catch (e) {
      console.warn("Supabase fetch warning, using local state:", e.message);
    }

    // LocalStorage / Default fallback
    try {
      const localProfile = localStorage.getItem("causalcut_user_profile");
      const localFactories = localStorage.getItem("causalcut_factories");
      if (localProfile) setUserProfile(JSON.parse(localProfile));
      else {
        setUserProfile({
          display_name: "N. Sharma",
          industry_name: "Steelforge Integrated Steel",
          industry_type: "steel",
          role: "shift_officer"
        });
      }

      if (localFactories) {
        setFactories(JSON.parse(localFactories));
      } else {
        const defaultFactories = [
          {
            id: "steelforge-001",
            name: "Steelforge Facility",
            location: "Sector 4 Industrial Corridor",
            industry_type: "steel",
            factory_floors: [{ count: 2 }],
            created_at: new Date().toISOString()
          }
        ];
        setFactories(defaultFactories);
        localStorage.setItem("causalcut_factories", JSON.stringify(defaultFactories));
      }
    } catch {
      /* noop */
    }
  }, []);

  // ── Bootstrap: resolve existing session ──────────────────────────────────
  useEffect(() => {
    supabase.auth.getSession()
      .then(({ data: { session: s } }) => {
        if (s) {
          setSession(s);
          if (s?.user?.id) loadUserData(s.user.id);
        } else {
          // Check local session
          const localSession = localStorage.getItem("causalcut_session");
          if (localSession) {
            const parsed = JSON.parse(localSession);
            setSession(parsed);
            loadUserData(parsed.user?.id || "local-user");
          }
        }
        setLoading(false);
      })
      .catch((err) => {
        console.warn("Auth getSession fallback:", err);
        const localSession = localStorage.getItem("causalcut_session");
        if (localSession) {
          const parsed = JSON.parse(localSession);
          setSession(parsed);
          loadUserData(parsed.user?.id || "local-user");
        }
        setLoading(false);
      });

    try {
      const { data: { subscription } } = supabase.auth.onAuthStateChange(
        (_event, s) => {
          if (s) {
            setSession(s);
            if (s?.user?.id) loadUserData(s.user.id);
          }
        }
      );
      return () => subscription?.unsubscribe?.();
    } catch {
      setLoading(false);
    }
  }, [loadUserData]);

  // ── Login (email + password with offline fallback) ──────────────────────
  const login = async (email, password) => {
    try {
      const { data, error } = await supabase.auth.signInWithPassword({ email, password });
      if (!error && data?.session) {
        setSession(data.session);
        return data;
      }
    } catch (err) {
      console.warn("Supabase login unavailable, activating local session:", err.message);
    }

    // Local fallback login
    const localUser = {
      id: "local-operator-" + Date.now(),
      email: email || "operator@steelforge.ai",
    };
    const localSession = { user: localUser, access_token: "local-dev-token" };
    const localProfile = {
      display_name: email ? email.split("@")[0] : "N. Sharma",
      industry_name: "Steelforge Integrated Steel",
      industry_type: "steel",
      role: "shift_officer"
    };

    localStorage.setItem("causalcut_session", JSON.stringify(localSession));
    localStorage.setItem("causalcut_user_profile", JSON.stringify(localProfile));
    setSession(localSession);
    setUserProfile(localProfile);
    loadUserData(localUser.id);
    return { session: localSession, user: localUser };
  };

  // ── Signup (with offline fallback) ──────────────────────────────────────
  const signup = async ({ email, password, displayName, industryName, industryType, role }) => {
    try {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: { data: { display_name: displayName } },
      });
      if (!error && data?.user) {
        await supabase.from("user_profiles").upsert({
          auth_id: data.user.id,
          display_name: displayName,
          email,
          industry_name: industryName,
          industry_type: industryType || "general",
          role: role || "admin",
        });
        return data;
      }
    } catch (err) {
      console.warn("Supabase signup unavailable, creating local user:", err.message);
    }

    // Local fallback signup
    const localUser = { id: "local-user-" + Date.now(), email };
    const localSession = { user: localUser, access_token: "local-dev-token" };
    const localProfile = {
      display_name: displayName || "Plant Administrator",
      industry_name: industryName || "Steelforge Plant",
      industry_type: industryType || "steel",
      role: role || "admin"
    };

    localStorage.setItem("causalcut_session", JSON.stringify(localSession));
    localStorage.setItem("causalcut_user_profile", JSON.stringify(localProfile));
    setSession(localSession);
    setUserProfile(localProfile);
    loadUserData(localUser.id);
    return { user: localUser, session: localSession };
  };

  // ── Logout ───────────────────────────────────────────────────────────────
  const logout = async () => {
    try {
      await supabase.auth.signOut();
    } catch {
      /* noop */
    }
    localStorage.removeItem("causalcut_session");
    localStorage.removeItem("causalcut_user_profile");
    setSession(null);
    setUserProfile(null);
    setFactories([]);
  };

  // ── Save a new factory (called by OnboardingFlow on completion) ──────────
  const addFactory = async (factoryData) => {
    const userId = session?.user?.id || "local-user";

    try {
      const { data: factory, error: fErr } = await supabase
        .from("factories")
        .insert({
          owner_id: userId,
          name: factoryData.name,
          location: factoryData.location,
          industry_type: factoryData.industryType || "general",
        })
        .select()
        .single();

      if (!fErr && factory) {
        await loadUserData(userId);
        return factory;
      }
    } catch (err) {
      console.warn("Supabase factory save fallback to local:", err.message);
    }

    // Local fallback factory save
    const newFactory = {
      id: "factory-" + Date.now(),
      name: factoryData.name || "Steelforge Plant",
      location: factoryData.location || "Industrial Zone",
      industry_type: factoryData.industryType || "steel",
      factory_floors: [{ count: factoryData.floors?.length || 1 }],
      created_at: new Date().toISOString()
    };

    const currentFactories = [...factories, newFactory];
    setFactories(currentFactories);
    localStorage.setItem("causalcut_factories", JSON.stringify(currentFactories));
    return newFactory;
  };

  // ── Refresh factories list ────────────────────────────────────────────────
  const refreshFactories = async () => {
    const uid = session?.user?.id || "local-user";
    await loadUserData(uid);
  };

  return (
    <AuthContext.Provider
      value={{
        session,
        userProfile,
        factories,
        loading,
        login,
        signup,
        logout,
        addFactory,
        refreshFactories,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}

// @refresh reset
import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { supabase } from "../lib/supabase";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => {
    try {
      const s = localStorage.getItem("causalcut_session");
      if (s) return JSON.parse(s);
    } catch {
      /* noop */
    }
    // Default demo operator session
    const defaultSession = {
      user: { id: "dev-operator-001", email: "operator@steelforge.ai" },
      access_token: "dev-operator-token"
    };
    try {
      localStorage.setItem("causalcut_session", JSON.stringify(defaultSession));
    } catch {
      /* noop */
    }
    return defaultSession;
  });
  const [userProfile, setUserProfile] = useState(() => {
    try {
      const p = localStorage.getItem("causalcut_user_profile");
      if (p) return JSON.parse(p);
    } catch {
      /* noop */
    }
    return {
      display_name: "N. Sharma",
      industry_name: "Steelforge Integrated Steel",
      industry_type: "steel",
      role: "shift_officer"
    };
  });
  const [factories, setFactories] = useState(() => {
    try {
      const f = localStorage.getItem("causalcut_factories");
      if (f) return JSON.parse(f);
    } catch {
      /* noop */
    }
    return [
      {
        id: "steelforge-001",
        name: "Steelforge Facility",
        location: "Sector 4 Industrial Corridor",
        industry_type: "steel",
        factory_floors: [{ count: 2 }],
        created_at: new Date().toISOString()
      }
    ];
  });
  const [loading, setLoading] = useState(false);

  // ── Fetch user data with local fallback ────────────────────────────────
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

    try {
      const localProfile = localStorage.getItem("causalcut_user_profile");
      const localFactories = localStorage.getItem("causalcut_factories");
      if (localProfile) setUserProfile(JSON.parse(localProfile));
      if (localFactories) setFactories(JSON.parse(localFactories));
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
        }
        setLoading(false);
      })
      .catch((err) => {
        console.warn("Auth getSession fallback:", err);
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

  // ── Save a new factory ───────────────────────────────────────────────────
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
        if (factoryData.floors?.length) {
          for (let i = 0; i < factoryData.floors.length; i++) {
            const floor = factoryData.floors[i];
            const { data: floorRow } = await supabase
              .from("factory_floors")
              .insert({
                factory_id: factory.id,
                floor_number: i + 1,
                floor_name: floor.floorName || `Floor ${i + 1}`,
                sort_order: i,
              })
              .select()
              .single();

            if (floorRow && floor.zones?.length) {
              const zoneRows = floor.zones.map((z) => ({
                factory_id: factory.id,
                floor_id: floorRow.id,
                zone_id: z.id,
                name: z.label || z.id,
                hazard_class: z.hazard_class || "general",
              }));
              await supabase.from("factory_zones").insert(zoneRows);
            }
          }
        }
        await loadUserData(userId);
        return factory;
      }
    } catch (e) {
      console.warn("Supabase factory save fallback:", e.message);
    }

    const newFactory = {
      id: "factory-" + Date.now(),
      name: factoryData.name || "Steelforge Facility",
      location: factoryData.location || "Sector 4 Industrial Corridor",
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
    if (session?.user?.id) await loadUserData(session.user.id);
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

// @refresh reset
import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { supabase } from "../lib/supabase";

const AuthContext = createContext(null);


export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);         // Supabase auth session
  const [userProfile, setUserProfile] = useState(null); // user_profiles row
  const [factories, setFactories] = useState([]);        // factories[] for this user
  const [loading, setLoading] = useState(true);          // resolving initial session

  // ── Fetch the user's profile + factories from Supabase ──────────────────
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
      if (factoriesRes.data) setFactories(factoriesRes.data);
    } catch (e) {
      console.warn("loadUserData:", e.message);
    }
  }, []);

  // ── Bootstrap: resolve existing session ──────────────────────────────────
  useEffect(() => {
    supabase.auth.getSession()
      .then(({ data: { session: s } }) => {
        setSession(s);
        if (s?.user?.id) loadUserData(s.user.id);
        setLoading(false);
      })
      .catch((err) => {
        console.warn("Auth getSession error:", err);
        setLoading(false);
      });

    try {
      const { data: { subscription } } = supabase.auth.onAuthStateChange(
        (_event, s) => {
          setSession(s);
          if (s?.user?.id) loadUserData(s.user.id);
          else {
            setUserProfile(null);
            setFactories([]);
          }
        }
      );
      return () => subscription?.unsubscribe?.();
    } catch {
      setLoading(false);
    }
  }, [loadUserData]);

  // ── Login (email + password) ─────────────────────────────────────────────
  const login = async (email, password) => {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
    return data;
  };

  // ── Signup (creates auth user + user_profile row) ────────────────────────
  const signup = async ({ email, password, displayName, industryName, industryType, role }) => {
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        emailRedirectTo: undefined,   // skip confirmation-email flow
        data: { display_name: displayName },
      },
    });
    if (error) throw error;

    // Insert profile row (may not exist yet if email confirmation is disabled)
    if (data.user) {
      await supabase.from("user_profiles").upsert({
        auth_id: data.user.id,
        display_name: displayName,
        email,
        industry_name: industryName,
        industry_type: industryType || "general",
        role: role || "admin",
      });
    }
    return data;
  };

  // ── Logout ───────────────────────────────────────────────────────────────
  const logout = async () => {
    await supabase.auth.signOut();
  };

  // ── Save a new factory (called by OnboardingFlow on completion) ──────────
  const addFactory = async (factoryData) => {
    const userId = session?.user?.id;
    if (!userId) throw new Error("Not authenticated");

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
    if (fErr) throw fErr;

    // Save each floor + its zones, sensors, and blueprint
    for (let i = 0; i < factoryData.floors.length; i++) {
      const floor = factoryData.floors[i];

      const { data: floorRow, error: floorErr } = await supabase
        .from("factory_floors")
        .insert({
          factory_id: factory.id,
          floor_number: i + 1,
          floor_name: floor.floorName || `Floor ${i + 1}`,
          sort_order: i,
        })
        .select()
        .single();
      if (floorErr) throw floorErr;

      // Upload blueprint image to Supabase Storage
      if (floor.blueprintDataUrl) {
        try {
          const blob = await (await fetch(floor.blueprintDataUrl)).blob();
          const filePath = `${userId}/${factory.id}/${floorRow.id}/blueprint.png`;
          const { error: upErr } = await supabase.storage
            .from("blueprints")
            .upload(filePath, blob, { upsert: true, contentType: "image/png" });

          if (!upErr) {
            await supabase.from("blueprints").insert({
              factory_id: factory.id,
              floor_id: floorRow.id,
              file_name: "blueprint.png",
              storage_path: filePath,
              mime_type: "image/png",
              uploaded_by: userId,
              extracted_json: {
                zones: floor.zones,
                zone_adjacency: floor.zone_adjacency,
                sensors: floor.sensors,
              },
            });
          }
        } catch (e) {
          console.warn("Blueprint upload failed (non-fatal):", e.message);
        }
      }

      // Save zones
      if (floor.zones?.length) {
        const zoneRows = floor.zones.map((z) => ({
          factory_id: factory.id,
          floor_id: floorRow.id,
          zone_id: z.id,
          name: z.label || z.id,
          hazard_class: z.hazard_class || "general",
        }));
        await supabase.from("factory_zones").insert(zoneRows);
      }

      // Save sensors
      if (floor.sensors?.length) {
        const sensorRows = floor.sensors.map((s) => ({
          factory_id: factory.id,
          floor_id: floorRow.id,
          sensor_id: s.id,
          sensor_type: s.type || "gas",
          zone_id: s.zone_id || null,
        }));
        await supabase.from("factory_sensors").insert(sensorRows);
      }
    }

    // Refresh local factories list
    await loadUserData(userId);
    return factory;
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

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import { getSession, saveSession, clearSession, fetchMe, startLogin } from "../api/broker";

const AuthContext = createContext();

const IS_DEMO = process.env.REACT_APP_DEMO_MODE === "true";

const DEMO_USER = {
  login: "Demo",
  name: "Demo User",
  avatarUrl: null,
};

// Demo session limits
const DEMO_SESSION_DURATION = 2 * 60; // 2 minutes in seconds (testing; raise to 15*60 for production)
const DEMO_COOLDOWN_DURATION = 2 * 60; // 2 minutes in seconds (testing; raise to 60*60 for production)
const DEMO_STORAGE_KEY = "ecoseek_demo_session";

function getDemoState() {
  try {
    const raw = localStorage.getItem(DEMO_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveDemoState(state) {
  localStorage.setItem(DEMO_STORAGE_KEY, JSON.stringify(state));
}

function clearDemoState() {
  localStorage.removeItem(DEMO_STORAGE_KEY);
}

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(!IS_DEMO);
  // Demo session state
  const [demoActive, setDemoActive] = useState(false);
  const [demoRemaining, setDemoRemaining] = useState(DEMO_SESSION_DURATION);
  const [demoCooldownRemaining, setDemoCooldownRemaining] = useState(0);
  const demoTimerRef = useRef(null);

  // Restore demo session on mount
  useEffect(() => {
    if (!IS_DEMO) return;
    setLoading(false);
    const state = getDemoState();
    if (!state) return;

    const now = Math.floor(Date.now() / 1000);

    if (state.cooldownUntil && now < state.cooldownUntil) {
      // Still in cooldown
      setDemoCooldownRemaining(state.cooldownUntil - now);
      return;
    }

    if (state.startedAt) {
      const elapsed = now - state.startedAt;
      const remaining = DEMO_SESSION_DURATION - elapsed;
      if (remaining > 0) {
        // Resume active session
        setUser(DEMO_USER);
        setDemoActive(true);
        setDemoRemaining(remaining);
      } else {
        // Session expired — enter cooldown
        const cooldownUntil = state.startedAt + DEMO_SESSION_DURATION + DEMO_COOLDOWN_DURATION;
        if (now < cooldownUntil) {
          saveDemoState({ cooldownUntil });
          setDemoCooldownRemaining(cooldownUntil - now);
        } else {
          clearDemoState();
        }
      }
    }
  }, []);

  // Tick demo session timer
  useEffect(() => {
    if (!IS_DEMO || !demoActive) return;
    demoTimerRef.current = setInterval(() => {
      setDemoRemaining((prev) => {
        if (prev <= 1) {
          // Session expired
          clearInterval(demoTimerRef.current);
          setDemoActive(false);
          setUser(null);
          const cooldownUntil = Math.floor(Date.now() / 1000) + DEMO_COOLDOWN_DURATION;
          saveDemoState({ cooldownUntil });
          setDemoCooldownRemaining(DEMO_COOLDOWN_DURATION);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(demoTimerRef.current);
  }, [demoActive]);

  // Tick cooldown timer
  useEffect(() => {
    if (!IS_DEMO || demoCooldownRemaining <= 0) return;
    const id = setInterval(() => {
      setDemoCooldownRemaining((prev) => {
        if (prev <= 1) {
          clearInterval(id);
          clearDemoState();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [demoCooldownRemaining]);

  const startDemoSession = useCallback(() => {
    if (!IS_DEMO) return;
    const now = Math.floor(Date.now() / 1000);
    saveDemoState({ startedAt: now });
    setUser(DEMO_USER);
    setDemoActive(true);
    setDemoRemaining(DEMO_SESSION_DURATION);
    setDemoCooldownRemaining(0);
  }, []);

  const checkAuth = useCallback(async () => {
    if (IS_DEMO) return;
    const session = getSession();
    if (!session?.session_id) {
      setUser(null);
      setLoading(false);
      return;
    }
    const me = await fetchMe();
    if (me?.user) {
      setUser(me.user);
    } else {
      clearSession();
      setUser(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const login = () => {
    if (IS_DEMO) return;
    startLogin(window.location.origin + "/callback");
  };

  const handleCallback = () => {
    if (IS_DEMO) return;
    const params = new URLSearchParams(window.location.search);
    const sid = params.get("session_id");
    if (sid) {
      saveSession(sid, null);
      window.history.replaceState({}, "", "/");
      checkAuth();
    }
  };

  const logout = () => {
    if (IS_DEMO) {
      clearInterval(demoTimerRef.current);
      setDemoActive(false);
      setUser(null);
      const cooldownUntil = Math.floor(Date.now() / 1000) + DEMO_COOLDOWN_DURATION;
      saveDemoState({ cooldownUntil });
      setDemoCooldownRemaining(DEMO_COOLDOWN_DURATION);
      return;
    }
    clearSession();
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        logout,
        handleCallback,
        // Demo-specific
        startDemoSession,
        demoActive,
        demoRemaining,
        demoCooldownRemaining,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
};

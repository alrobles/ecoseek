import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { getSession, saveSession, clearSession, fetchMe, startLogin } from "../api/broker";

const AuthContext = createContext();

const IS_DEMO = process.env.REACT_APP_DEMO_MODE === "true";

const DEMO_USER = {
  login: "Demo",
  name: "Demo User",
  avatarUrl: null,
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(IS_DEMO ? DEMO_USER : null);
  const [loading, setLoading] = useState(!IS_DEMO);

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
    if (IS_DEMO) return;
    clearSession();
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{ user, loading, login, logout, handleCallback }}
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

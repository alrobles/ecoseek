import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { getSession, saveSession, clearSession, fetchMe, startLogin } from "../api/broker";

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
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
    startLogin(window.location.origin + "/callback");
  };

  const handleCallback = () => {
    const params = new URLSearchParams(window.location.search);
    const sid = params.get("session_id");
    if (sid) {
      saveSession(sid, null);
      window.history.replaceState({}, "", "/");
      checkAuth();
    }
  };

  const logout = () => {
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

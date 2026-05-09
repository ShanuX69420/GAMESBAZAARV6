'use client';

import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE } from '@/lib/config';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const getToken = useCallback(() => null, []);

  const logout = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/api/auth/logout/`, {
        method: 'POST',
        credentials: 'include',
      });
    } finally {
      setUser(null);
    }
  }, []);

  const fetchUser = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/me/`, {
        credentials: 'include',
      });
      if (res.ok) {
        const data = await res.json();
        setUser(data);
        return data;
      } else {
        const refreshRes = await fetch(`${API_BASE}/api/auth/refresh/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({}),
        });
        if (refreshRes.ok) {
          const retryRes = await fetch(`${API_BASE}/api/auth/me/`, {
            credentials: 'include',
          });
          if (retryRes.ok) {
            const data = await retryRes.json();
            setUser(data);
            return data;
          }
        }
        await logout();
        return null;
      }
    } catch {
      await logout();
      return null;
    } finally {
      setLoading(false);
    }
  }, [logout]);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = useCallback(async (email, password) => {
    const res = await fetch(`${API_BASE}/api/auth/login/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Login failed');
    }
    return fetchUser();
  }, [fetchUser]);

  const googleLogin = useCallback(async (credential) => {
    const res = await fetch(`${API_BASE}/api/auth/google/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ credential }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Google sign-in failed');
    }
    return fetchUser();
  }, [fetchUser]);

  const register = useCallback(async (username, email, password, password2) => {
    const res = await fetch(`${API_BASE}/api/auth/register/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, email, password, password2 }),
    });
    const data = await res.json();
    if (!res.ok) {
      // Extract first error message
      const errors = Object.values(data).flat();
      throw new Error(errors[0] || 'Registration failed');
    }
    return data;
  }, []);

  const value = useMemo(() => ({
    user,
    loading,
    login,
    googleLogin,
    register,
    logout,
    getToken,
    fetchUser,
  }), [user, loading, login, googleLogin, register, logout, getToken, fetchUser]);

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}

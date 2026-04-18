'use client';

import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const getToken = () => {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem('gb_access_token');
  };

  const fetchUser = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/auth/me/`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setUser(data);
      } else {
        // Token expired, try refresh
        const refreshToken = localStorage.getItem('gb_refresh_token');
        if (refreshToken) {
          const refreshRes = await fetch(`${API_BASE}/api/auth/refresh/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh: refreshToken }),
          });
          if (refreshRes.ok) {
            const tokens = await refreshRes.json();
            localStorage.setItem('gb_access_token', tokens.access);
            if (tokens.refresh) localStorage.setItem('gb_refresh_token', tokens.refresh);
            // Retry fetching user
            const retryRes = await fetch(`${API_BASE}/api/auth/me/`, {
              headers: { 'Authorization': `Bearer ${tokens.access}` },
            });
            if (retryRes.ok) {
              setUser(await retryRes.json());
            } else {
              logout();
            }
          } else {
            logout();
          }
        } else {
          logout();
        }
      }
    } catch {
      logout();
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = async (username, password) => {
    const res = await fetch(`${API_BASE}/api/auth/login/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Login failed');
    }
    localStorage.setItem('gb_access_token', data.access);
    localStorage.setItem('gb_refresh_token', data.refresh);
    await fetchUser();
    return data;
  };

  const register = async (username, email, password, password2) => {
    const res = await fetch(`${API_BASE}/api/auth/register/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password, password2 }),
    });
    const data = await res.json();
    if (!res.ok) {
      // Extract first error message
      const errors = Object.values(data).flat();
      throw new Error(errors[0] || 'Registration failed');
    }
    return data;
  };

  const logout = () => {
    localStorage.removeItem('gb_access_token');
    localStorage.removeItem('gb_refresh_token');
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, getToken, fetchUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}

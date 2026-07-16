'use client';

import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE } from '@/lib/config';
import { requestLogout } from '@/lib/authRequests';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const getToken = useCallback(() => null, []);

  const logout = useCallback(async () => {
    await requestLogout();
    setUser(null);
  }, []);

  const fetchUser = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/me/`, {
        credentials: 'include',
      });
      if (res.status === 204) {
        setUser(null);
        return null;
      }
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

  // Pre-paint hint for the NEXT page load: the inline script in app/layout.js
  // reads gb_auth_hint and hides guest-only UI (navbar Login/Sign Up, home
  // CTA) before first paint, so returning logged-in users get neither a
  // flash nor a layout shift. Also corrects the current page when the hint
  // was stale (e.g. logged out elsewhere).
  useEffect(() => {
    if (loading) return;
    try { localStorage.setItem('gb_auth_hint', user ? '1' : '0'); } catch {}
    if (user) {
      document.documentElement.dataset.authHint = '1';
    } else {
      delete document.documentElement.dataset.authHint;
    }
  }, [user, loading]);

  const login = useCallback(async (email, password) => {
    const res = await fetch(`${API_BASE}/api/auth/login/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      const err = new Error(data.detail || 'Login failed');
      err.emailUnverified = data.email_unverified || false;
      throw err;
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
    // If user needs to complete profile setup (Google sign-up)
    if (data.needs_setup) {
      const userData = await fetchUser();
      return { ...userData, needs_setup: true };
    }
    return fetchUser();
  }, [fetchUser]);

  const register = useCallback(async (username, email, password, password2, acceptedTerms) => {
    const res = await fetch(`${API_BASE}/api/auth/register/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, email, password, password2, accepted_terms: acceptedTerms }),
    });
    const data = await res.json();
    if (!res.ok) {
      // Extract first error message
      const errors = Object.values(data).flat();
      throw new Error(errors[0] || 'Registration failed');
    }
    // Return verification token and message (user is inactive until verified)
    return data;
  }, []);

  const completeProfile = useCallback(async (username, acceptedTerms) => {
    const res = await fetch(`${API_BASE}/api/auth/complete-profile/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, accepted_terms: acceptedTerms }),
    });
    const data = await res.json();
    if (!res.ok) {
      const errors = Object.values(data).flat();
      throw new Error(errors[0] || 'Profile setup failed');
    }
    // Refresh user data after completing profile
    return fetchUser();
  }, [fetchUser]);

  const value = useMemo(() => ({
    user,
    loading,
    login,
    googleLogin,
    register,
    logout,
    getToken,
    fetchUser,
    completeProfile,
  }), [user, loading, login, googleLogin, register, logout, getToken, fetchUser, completeProfile]);

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

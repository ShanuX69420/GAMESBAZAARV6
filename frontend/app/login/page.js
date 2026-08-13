'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { trackSignUp } from '@/lib/analytics';
import { postLoginPath, readNextParam, withNext } from '@/lib/loginRedirect';
import GoogleSignInButton from '@/components/GoogleSignInButton';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [emailUnverified, setEmailUnverified] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  // Read after mount, not with useSearchParams — see lib/loginRedirect.js.
  const [nextPath, setNextPath] = useState(null);
  const { user, loading, login } = useAuth();
  const router = useRouter();

  useEffect(() => {
    setNextPath(readNextParam());
  }, []);

  useEffect(() => {
    if (!loading && user) {
      const next = readNextParam();
      if (user.needs_setup) {
        router.replace(withNext('/complete-profile', next));
      } else {
        router.replace(postLoginPath(next, user));
      }
    }
  }, [user, loading, router]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setEmailUnverified(false);
    setSubmitting(true);
    try {
      const userData = await login(email, password);
      router.push(postLoginPath(nextPath, userData));
    } catch (err) {
      if (err.emailUnverified) {
        setEmailUnverified(true);
        setError(err.message || 'Please verify your email address before signing in.');
      } else {
        setError(err.message || 'Invalid credentials');
      }
    } finally {
      setSubmitting(false);
    }
  }

  function handleGoogleSuccess(userData) {
    if (userData?.needs_setup) {
      // needs_setup marks accounts that haven't finished onboarding — i.e. new.
      trackSignUp('google');
      router.push(withNext('/complete-profile', nextPath));
    } else {
      router.push(postLoginPath(nextPath, userData));
    }
  }

  function handleGoogleError(message) {
    setError(message);
  }

  // The form renders during the auth check so it's in the server HTML —
  // swapping a full-page spinner for the form shoved the footer down and was
  // a real mobile CLS hit. Logged-in visitors (rare here) see the form
  // briefly until the effect above redirects them.
  if (user) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  return (
    <div className="container">
      <div className="auth-page">
        <div className="auth-card">
          <h1 className="auth-title">Welcome Back</h1>
          <p className="auth-subtitle">Sign in to your GamesBazaar account</p>

          {error && (
            <div className="alert alert-error">
              {error}
              {emailUnverified && (
                <>
                  {' '}
                  <Link href={withNext(`/verify-email?email=${encodeURIComponent(email)}`, nextPath)} style={{ fontWeight: 600 }}>
                    Verify now →
                  </Link>
                </>
              )}
            </div>
          )}

          <form onSubmit={handleSubmit} className="auth-form">
            <div className="form-group">
              <label className="form-label">Email</label>
              <input
                type="email"
                className="form-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter your email"
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Password</label>
              <input
                type="password"
                className="form-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                required
              />
            </div>

            <div className="auth-forgot-link">
              <Link href="/forgot-password">Forgot password?</Link>
            </div>

            <button type="submit" className="btn btn-primary btn-full" disabled={submitting}>
              {submitting ? 'Signing in...' : 'Sign In'}
            </button>
          </form>

          <GoogleSignInButton
            onSuccess={handleGoogleSuccess}
            onError={handleGoogleError}
          />

          <p className="auth-footer">
            Don&apos;t have an account? <Link href={withNext('/register', nextPath)}>Sign Up</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

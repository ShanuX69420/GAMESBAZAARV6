'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import GoogleSignInButton from '@/components/GoogleSignInButton';

export default function RegisterPage() {
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: '',
    password2: '',
  });
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const { user, loading, register } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) {
      if (user.needs_setup) {
        router.replace('/complete-profile');
      } else {
        router.replace('/');
      }
    }
  }, [user, loading, router]);

  function handleChange(e) {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const data = await register(
        formData.username,
        formData.email,
        formData.password,
        formData.password2,
        acceptedTerms
      );
      // Redirect to verify-email page with token and email
      const params = new URLSearchParams({
        token: data.verification_token,
        email: formData.email,
      });
      router.push(`/verify-email?${params.toString()}`);
    } catch (err) {
      setError(err.message || 'Registration failed');
    } finally {
      setSubmitting(false);
    }
  }

  function handleGoogleSuccess(userData) {
    if (userData?.needs_setup) {
      router.push('/complete-profile');
    } else {
      router.push(userData?.is_seller ? '/dashboard' : '/');
    }
  }

  function handleGoogleError(message) {
    setError(message);
  }

  if (loading || user) {
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
          <h1 className="auth-title">Create Account</h1>
          <p className="auth-subtitle">Join Pakistan&apos;s gaming marketplace</p>

          {error && <div className="alert alert-error">{error}</div>}

          <form onSubmit={handleSubmit} className="auth-form">
            <div className="form-group">
              <label className="form-label">Display name</label>
              <input
                type="text"
                name="username"
                className="form-input"
                value={formData.username}
                onChange={handleChange}
                placeholder="Choose your public name"
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Email</label>
              <input
                type="email"
                name="email"
                className="form-input"
                value={formData.email}
                onChange={handleChange}
                placeholder="your@email.com"
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Password</label>
              <input
                type="password"
                name="password"
                className="form-input"
                value={formData.password}
                onChange={handleChange}
                placeholder="Min. 6 characters"
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Confirm Password</label>
              <input
                type="password"
                name="password2"
                className="form-input"
                value={formData.password2}
                onChange={handleChange}
                placeholder="Repeat your password"
                required
              />
            </div>

            <div className="terms-checkbox-group">
              <input
                type="checkbox"
                id="register-accept-terms"
                className="terms-checkbox"
                checked={acceptedTerms}
                onChange={(e) => setAcceptedTerms(e.target.checked)}
              />
              <label htmlFor="register-accept-terms" className="terms-label">
                I agree to the{' '}
                <Link href="/terms-of-service" target="_blank">Terms of Service</Link>
                {' '}and{' '}
                <Link href="/privacy-policy" target="_blank">Privacy Policy</Link>
              </label>
            </div>

            <button type="submit" className="btn btn-primary btn-full" disabled={submitting || !acceptedTerms}>
              {submitting ? 'Creating Account...' : 'Create Account'}
            </button>
          </form>

          <GoogleSignInButton
            onSuccess={handleGoogleSuccess}
            onError={handleGoogleError}
          />

          <p className="auth-footer">
            Already have an account? <Link href="/login">Sign In</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

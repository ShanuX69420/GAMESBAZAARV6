'use client';

import { useEffect, useState, useCallback, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { API_BASE } from '@/lib/config';

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [token, setToken] = useState(searchParams.get('token') || '');
  const [email] = useState(searchParams.get('email') || '');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);
  const [resending, setResending] = useState(false);

  // Countdown timer for resend button
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = setTimeout(() => setResendCooldown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [resendCooldown]);

  const handleSubmit = useCallback(async (e) => {
    e.preventDefault();
    if (!token || !code.trim()) {
      setError('Please enter the verification code.');
      return;
    }
    setError('');
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/verify-email/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ token, code: code.trim() }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || 'Verification failed. Please try again.');
        return;
      }
      setSuccess(true);
    } catch {
      setError('Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }, [token, code]);

  const handleResend = useCallback(async () => {
    if (!email || resendCooldown > 0) return;
    setResending(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/auth/resend-verification/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (res.ok && data.verification_token) {
        setToken(data.verification_token);
        setCode('');
      }
      setResendCooldown(60);
    } catch {
      setError('Failed to resend code. Please try again.');
    } finally {
      setResending(false);
    }
  }, [email, resendCooldown]);

  // Auto-submit when 6 digits are entered
  const handleCodeChange = useCallback((e) => {
    const val = e.target.value.replace(/\D/g, '').slice(0, 6);
    setCode(val);
  }, []);

  if (!token && !email) {
    return (
      <div className="container">
        <div className="auth-page">
          <div className="auth-card" style={{ textAlign: 'center' }}>
            <div className="verify-email-icon">⚠️</div>
            <h1 className="auth-title">Invalid Link</h1>
            <p className="auth-subtitle">This verification link is invalid or has expired.</p>
            <Link href="/register" className="btn btn-primary btn-full" style={{ marginTop: '16px' }}>
              Create New Account
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (success) {
    return (
      <div className="container">
        <div className="auth-page">
          <div className="auth-card" style={{ textAlign: 'center' }}>
            <div className="verify-success-icon">✅</div>
            <h1 className="auth-title">Email Verified!</h1>
            <p className="auth-subtitle">
              Your email has been verified successfully. You can now sign in to your account.
            </p>
            <Link href="/login" className="btn btn-primary btn-full" style={{ marginTop: '16px' }}>
              Sign In
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="container">
      <div className="auth-page">
        <div className="auth-card">
          <div className="verify-email-icon">📧</div>
          <h1 className="auth-title" style={{ textAlign: 'center' }}>Verify Your Email</h1>
          <p className="auth-subtitle" style={{ textAlign: 'center' }}>
            {token
              ? 'We sent a 6-digit verification code to your email'
              : 'Request a new verification code to finish creating your account.'}
          </p>
          {email && (
            <p className="verify-email-hint">
              {token ? 'Check' : 'We will send it to'}{' '}
              <span className="verify-email-highlight">{email}</span>
            </p>
          )}

          {error && <div className="alert alert-error">{error}</div>}

          {token && (
            <form onSubmit={handleSubmit} className="auth-form" style={{ marginTop: '20px' }}>
              <div className="form-group">
                <input
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  className="verify-code-input"
                  value={code}
                  onChange={handleCodeChange}
                  placeholder="000000"
                  maxLength={6}
                  autoFocus
                />
              </div>

              <button
                type="submit"
                className="btn btn-primary btn-full"
                disabled={submitting || code.length !== 6}
              >
                {submitting ? 'Verifying...' : 'Verify Email'}
              </button>
            </form>
          )}

          <div className="verify-resend-row">
            <span>{token ? 'Didn\u0027t receive the code?' : 'Ready to continue?'}</span>
            {resendCooldown > 0 ? (
              <span className="verify-countdown">Resend in {resendCooldown}s</span>
            ) : (
              <button
                type="button"
                className="verify-resend-btn"
                onClick={handleResend}
                disabled={resending || !email}
              >
                {resending ? 'Sending...' : token ? 'Resend Code' : 'Send Code'}
              </button>
            )}
          </div>

          <p className="auth-footer">
            Wrong email? <Link href="/register">Create New Account</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    }>
      <VerifyEmailContent />
    </Suspense>
  );
}

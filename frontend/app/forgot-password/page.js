'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { requestPasswordReset, confirmPasswordReset } from '@/lib/api';
import { CheckCircleIcon } from '@/lib/icons';

export default function ForgotPasswordPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  const [step, setStep] = useState('email'); // email | code | done
  const [email, setEmail] = useState('');
  const [token, setToken] = useState('');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newPassword2, setNewPassword2] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!loading && user) router.replace('/');
  }, [user, loading, router]);

  // Step 1: Request reset code
  async function handleRequestCode(e) {
    e.preventDefault();
    if (!email.trim()) return;
    setSubmitting(true); setError(''); setMessage('');
    try {
      const data = await requestPasswordReset(email.trim());
      setToken(data.token || '');
      setStep('code');
      setMessage(data.message || 'If that email exists, a reset code has been sent.');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  // Step 2: Verify code and set new password
  async function handleResetPassword(e) {
    e.preventDefault();
    if (newPassword !== newPassword2) { setError('Passwords do not match.'); return; }
    if (code.length !== 6) { setError('Enter the 6-digit code.'); return; }
    setSubmitting(true); setError(''); setMessage('');
    try {
      const data = await confirmPasswordReset(token, code.trim(), newPassword, newPassword2);
      setStep('done');
      setMessage(data.message);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
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
          {step === 'email' && (
            <>
              <h1 className="auth-title">Forgot Password?</h1>
              <p className="auth-subtitle">Enter your email and we&apos;ll send you a reset code</p>

              {error && <div className="alert alert-error">{error}</div>}
              {message && <div className="alert alert-success">{message}</div>}

              <form onSubmit={handleRequestCode} className="auth-form">
                <div className="form-group">
                  <label className="form-label">Email Address</label>
                  <input
                    type="email"
                    className="form-input"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="Enter your email"
                    required
                    autoFocus
                  />
                </div>
                <button type="submit" className="btn btn-primary btn-full" disabled={submitting}>
                  {submitting ? 'Sending...' : 'Send Reset Code'}
                </button>
              </form>

              <p className="auth-footer">
                Remember your password? <Link href="/login">Sign In</Link>
              </p>
            </>
          )}

          {step === 'code' && (
            <>
              <h1 className="auth-title">Check Your Email</h1>
              <p className="auth-subtitle">
                Enter the 6-digit code sent to <strong>{email}</strong>
              </p>

              {error && <div className="alert alert-error">{error}</div>}
              {message && <div className="alert alert-success">{message}</div>}

              <form onSubmit={handleResetPassword} className="auth-form">
                <div className="form-group">
                  <label className="form-label">Verification Code</label>
                  <input
                    type="text"
                    className="form-input"
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    placeholder="000000"
                    maxLength={6}
                    autoFocus
                    style={{ textAlign: 'center', letterSpacing: '0.3em', fontSize: '1.3rem', fontWeight: 700, padding: '14px' }}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">New Password</label>
                  <div className="form-input-wrapper">
                    <input
                      type={showPw ? 'text' : 'password'}
                      className="form-input"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      placeholder="Enter new password"
                      required
                      minLength={6}
                    />
                    <button type="button" className="form-pw-toggle" onClick={() => setShowPw(!showPw)} aria-label={showPw ? 'Hide password' : 'Show password'}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
                        {showPw ? <><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></> : <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></>}
                      </svg>
                    </button>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Confirm New Password</label>
                  <input
                    type={showPw ? 'text' : 'password'}
                    className="form-input"
                    value={newPassword2}
                    onChange={(e) => setNewPassword2(e.target.value)}
                    placeholder="Confirm new password"
                    required
                    minLength={6}
                  />
                  {newPassword && newPassword2 && newPassword !== newPassword2 && (
                    <p style={{ color: 'var(--red-500)', fontSize: '0.78rem', marginTop: 4 }}>Passwords do not match</p>
                  )}
                </div>

                {newPassword && (
                  <div className="settings-pw-strength">
                    <div className="settings-pw-strength-bar">
                      <div className={`settings-pw-strength-fill ${newPassword.length >= 12 ? 'pw-strong' : newPassword.length >= 8 ? 'pw-medium' : 'pw-weak'}`}
                        style={{ width: `${Math.min(100, (newPassword.length / 12) * 100)}%` }}></div>
                    </div>
                    <span className="settings-pw-strength-text">{newPassword.length >= 12 ? 'Strong' : newPassword.length >= 8 ? 'Medium' : 'Weak'}</span>
                  </div>
                )}

                <button type="submit" className="btn btn-primary btn-full" disabled={submitting || code.length !== 6 || !newPassword || !newPassword2}>
                  {submitting ? 'Resetting...' : 'Reset Password'}
                </button>
              </form>

              <p className="auth-footer">
                <button type="button" className="auth-link-btn" onClick={() => { setStep('email'); setCode(''); setError(''); setMessage(''); }}>
                  ← Back to email
                </button>
              </p>
            </>
          )}

          {step === 'done' && (
            <>
              <div className="forgot-pw-icon"><CheckCircleIcon size={40} /></div>
              <h1 className="auth-title">Password Reset!</h1>
              <p className="auth-subtitle">{message || 'Your password has been reset successfully.'}</p>
              <Link href="/login" className="btn btn-primary btn-full" style={{ marginTop: 16 }}>
                Sign In
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

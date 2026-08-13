'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { postLoginPath, readNextParam, withNext } from '@/lib/loginRedirect';

export default function CompleteProfilePage() {
  const { user, loading, completeProfile } = useAuth();
  const router = useRouter();

  const [username, setUsername] = useState('');
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  // Read after mount, not with useSearchParams — see lib/loginRedirect.js.
  const [nextPath, setNextPath] = useState(null);

  useEffect(() => {
    setNextPath(readNextParam());
  }, []);

  // Redirect if not logged in or setup already done
  useEffect(() => {
    if (!loading) {
      const next = readNextParam();
      if (!user) {
        router.replace(withNext('/login', next));
      } else if (!user.needs_setup) {
        router.replace(next || '/');
      }
    }
  }, [user, loading, router]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');

    if (!username.trim()) {
      setError('Please choose a username.');
      return;
    }
    if (!acceptedTerms) {
      setError('You must accept the Terms of Service and Privacy Policy.');
      return;
    }

    setSubmitting(true);
    try {
      const userData = await completeProfile(username.trim(), acceptedTerms);
      router.push(postLoginPath(nextPath, userData));
    } catch (err) {
      setError(err.message || 'Failed to complete setup');
    } finally {
      setSubmitting(false);
    }
  }

  if (loading || !user || !user.needs_setup) {
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
          <h1 className="auth-title" style={{ textAlign: 'center' }}>Complete Your Profile</h1>
          <p className="auth-subtitle" style={{ textAlign: 'center' }}>
            Choose a username and accept our terms to get started
          </p>

          {error && <div className="alert alert-error">{error}</div>}

          <form onSubmit={handleSubmit} className="auth-form">
            <div className="form-group">
              <label className="form-label">Username</label>
              <input
                type="text"
                className="form-input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Choose your public name"
                maxLength={150}
                autoFocus
                required
              />
              <p className="setup-info-text">
                This is how other users will see you on GamesBazaar
              </p>
            </div>

            <div className="terms-checkbox-group">
              <input
                type="checkbox"
                id="accept-terms"
                className="terms-checkbox"
                checked={acceptedTerms}
                onChange={(e) => setAcceptedTerms(e.target.checked)}
              />
              <label htmlFor="accept-terms" className="terms-label">
                I agree to the{' '}
                <Link href="/terms-of-service" target="_blank">Terms of Service</Link>
                {' '}and{' '}
                <Link href="/privacy-policy" target="_blank">Privacy Policy</Link>
              </label>
            </div>

            <button
              type="submit"
              className="btn btn-primary btn-full"
              disabled={submitting || !acceptedTerms || !username.trim()}
            >
              {submitting ? 'Setting Up...' : 'Complete Setup'}
            </button>
          </form>

          <p className="setup-info-text" style={{ marginTop: '16px' }}>
            Signed in with Google as {user.email}
          </p>
        </div>
      </div>
    </div>
  );
}

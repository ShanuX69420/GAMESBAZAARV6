'use client';

import { useEffect } from 'react';
import Link from 'next/link';

export default function Error({ error, reset }) {
  useEffect(() => {
    console.error('Application error:', error);
  }, [error]);

  return (
    <div className="container">
      <div className="error-page">
        <div className="error-visual">
          <div className="error-code-display">
            <span className="error-digit">5</span>
            <span className="error-digit error-digit-accent">
              <svg width="80" height="80" viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="40" cy="40" r="36" stroke="currentColor" strokeWidth="4" />
                <path d="M28 28l8 8m-8 0l8-8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                <path d="M44 28l8 8m-8 0l8-8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                <path d="M28 54c4-6 20-6 24 0" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
              </svg>
            </span>
            <span className="error-digit">0</span>
          </div>
        </div>

        <h1 className="error-title">Something went wrong</h1>
        <p className="error-description">
          An unexpected error occurred. Don&apos;t worry — your data is safe. Try again or head back home.
        </p>

        <div className="error-actions">
          <button onClick={() => reset()} className="btn btn-primary error-btn-home">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
            Try Again
          </button>
          <Link href="/" className="btn btn-outline error-btn-support">
            Back to Home
          </Link>
        </div>

        {process.env.NODE_ENV === 'development' && error?.message && (
          <details className="error-details">
            <summary className="error-details-summary">Error Details (dev only)</summary>
            <pre className="error-details-pre">{error.message}{error.stack ? `\n\n${error.stack}` : ''}</pre>
          </details>
        )}
      </div>
    </div>
  );
}

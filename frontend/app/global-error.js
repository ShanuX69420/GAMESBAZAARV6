'use client';

import { useEffect } from 'react';

export default function GlobalError({ error, reset }) {
  useEffect(() => {
    console.error('Global error:', error);
  }, [error]);

  return (
    <html lang="en">
      <head>
        <title>Something went wrong — GamesBazaar</title>
        <link rel="icon" href="/icons/icon-96x96.png" />
        <style>{`
          *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
          body {
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            color: #111827;
            background: #FFFFFF;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            -webkit-font-smoothing: antialiased;
          }
          .ge-container {
            text-align: center;
            padding: 40px 24px;
            max-width: 480px;
          }
          .ge-logo {
            width: 48px;
            height: 48px;
            margin: 0 auto 24px;
          }
          .ge-logo-mark {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 8px;
            background: linear-gradient(135deg, #22C55E, #15803D);
            color: #fff;
            font-size: 0.95rem;
            font-weight: 800;
            letter-spacing: 0;
            line-height: 1;
            box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.32);
          }
          .ge-icon {
            font-size: 4rem;
            margin-bottom: 16px;
            opacity: 0.3;
          }
          .ge-title {
            font-size: 1.5rem;
            font-weight: 700;
            margin-bottom: 8px;
          }
          .ge-desc {
            font-size: 0.95rem;
            color: #6B7280;
            line-height: 1.6;
            margin-bottom: 28px;
          }
          .ge-actions {
            display: flex;
            gap: 12px;
            justify-content: center;
            flex-wrap: wrap;
          }
          .ge-btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 24px;
            font-size: 0.9rem;
            font-weight: 600;
            font-family: inherit;
            border-radius: 9999px;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
          }
          .ge-btn-primary {
            background: #22C55E;
            color: #fff;
            border: none;
          }
          .ge-btn-primary:hover { background: #16A34A; }
          .ge-btn-outline {
            background: #fff;
            color: #111827;
            border: 1px solid #E5E7EB;
          }
          .ge-btn-outline:hover { border-color: #D1D5DB; background: #F8FAF9; }
        `}</style>
      </head>
      <body>
        <div className="ge-container">
          <span className="ge-logo ge-logo-mark" aria-hidden="true">GB</span>
          <div className="ge-icon">⚠️</div>
          <h1 className="ge-title">Something went wrong</h1>
          <p className="ge-desc">
            A critical error occurred. This is usually temporary — please try again.
          </p>
          <div className="ge-actions">
            <button onClick={() => reset()} className="ge-btn ge-btn-primary">
              Try Again
            </button>
            <a href="/" className="ge-btn ge-btn-outline">
              Go to Home
            </a>
          </div>
        </div>
      </body>
    </html>
  );
}

// Server-side error monitoring for the Next.js runtime.
// Inert until NEXT_PUBLIC_SENTRY_DSN (or SENTRY_DSN) is set.
import * as Sentry from '@sentry/nextjs';

export async function register() {
  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN || process.env.SENTRY_DSN;
  if (dsn) {
    Sentry.init({
      dsn,
      environment: process.env.NODE_ENV === 'production' ? 'production' : 'development',
      sendDefaultPii: false,
      tracesSampleRate: 0,
      // Vulnerability scanners replay the site's own client-navigation
      // requests with garbage in the Next-Router-State-Tree header, and Next
      // rejects each one with a 500 (error codes E10 / E142). Real browsers
      // only send that header from Next's own router, so these are never a
      // real visitor. One scan on 2026-09-08 produced 477 such events.
      ignoreErrors: [
        'The router state header was sent but could not be parsed.',
        'The router state header was too large.',
      ],
    });
  }
}

export const onRequestError = Sentry.captureRequestError;

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
    });
  }
}

export const onRequestError = Sentry.captureRequestError;

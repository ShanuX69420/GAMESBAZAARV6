// Browser-side error monitoring. Inert until NEXT_PUBLIC_SENTRY_DSN is set.
import * as Sentry from '@sentry/nextjs';

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NODE_ENV === 'production' ? 'production' : 'development',
    sendDefaultPii: false,
    tracesSampleRate: 0,
    // Android in-app browsers (Google/Facebook/Instagram WebViews) inject a
    // Java-JS bridge into every page; it throws these when the host app is
    // torn down mid-call. Third-party noise, not our code.
    ignoreErrors: [
      'Java object is gone',
      'Java exception was raised during method invocation',
    ],
  });
}

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;

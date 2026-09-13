// Browser-side error monitoring. Inert until NEXT_PUBLIC_SENTRY_DSN is set.
//
// The SDK is loaded in idle time, not at startup: bundled statically it was
// ~40% of the page's main JavaScript chunk, whose evaluation was one of the
// long main-thread tasks a tap could queue behind on a budget phone (Search
// Console mobile INP > 200 ms, 2026-09-13). Next's own guidance is to keep
// this file light. Errors thrown before the SDK arrives are buffered by the
// two listeners below and reported once it has initialised.
import { runWhenIdle } from '@/lib/idle';

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

let sentry = null;
const earlyErrors = [];

function bufferError(event) {
  if (earlyErrors.length < 20) earlyErrors.push(event);
}

function initSentry(Sentry) {
  Sentry.init({
    dsn,
    environment: process.env.NODE_ENV === 'production' ? 'production' : 'development',
    sendDefaultPii: false,
    // Errors only, no performance tracing. The Next SDK adds its
    // BrowserTracing integration by default, and even at a 0% sample rate it
    // instruments fetch/XHR/history and watches every interaction, long task
    // and web vital - main-thread work on every tap for spans nobody sends.
    // Dropping the integration is what turns that off; `tracesSampleRate: 0`
    // alone did not.
    integrations: (defaults) => defaults.filter((integration) => integration.name !== 'BrowserTracing'),
    // Android in-app browsers (Google/Facebook/Instagram WebViews) inject a
    // Java-JS bridge into every page; it throws these when the host app is
    // torn down mid-call. Third-party noise, not our code.
    ignoreErrors: [
      'Java object is gone',
      'Java exception was raised during method invocation',
    ],
  });
  sentry = Sentry;
  window.removeEventListener('error', bufferError);
  window.removeEventListener('unhandledrejection', bufferError);
  for (const event of earlyErrors.splice(0)) {
    if (event.type === 'unhandledrejection') {
      Sentry.captureException(event.reason, { mechanism: { type: 'onunhandledrejection', handled: false } });
    } else {
      Sentry.captureException(event.error || new Error(event.message), { mechanism: { type: 'onerror', handled: false } });
    }
  }
}

if (dsn && typeof window !== 'undefined') {
  window.addEventListener('error', bufferError);
  window.addEventListener('unhandledrejection', bufferError);
  runWhenIdle(() => {
    import('@sentry/nextjs').then(initSentry).catch(() => {});
  });
}

// Next calls this on every client navigation. It only feeds Sentry's
// navigation tracing, which is off, so it is a no-op until the SDK loads and
// stays cheap after.
export function onRouterTransitionStart(...args) {
  if (sentry && typeof sentry.captureRouterTransitionStart === 'function') {
    sentry.captureRouterTransitionStart(...args);
  }
}

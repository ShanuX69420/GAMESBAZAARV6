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
    ignoreErrors: [
      // Android in-app browsers (Google/Facebook/Instagram WebViews) inject a
      // Java-JS bridge into every page; it throws these when the host app is
      // torn down mid-call. Third-party noise, not our code.
      'Java object is gone',
      'Java exception was raised during method invocation',
      // The browser fires this on `window` when a ResizeObserver callback
      // changes layout and would need another pass in the same frame; it
      // defers that pass to the next frame and reports the deferral as an
      // error. Nothing fails and nothing is lost. Neither our code nor our
      // shipped dependencies create a ResizeObserver, so it comes from an
      // extension, a WebView or a third-party script. First seen 2026-09-15
      // (older Chromium wording); the second string is the current wording.
      'ResizeObserver loop limit exceeded',
      'ResizeObserver loop completed with undelivered notifications',
      // Snapchat's iOS in-app browser injects a script into every page that
      // calls its own native bridge (their typo, not ours) and throws when
      // the bridge is not there. The page is unaffected: first seen
      // 2026-09-20, twice, both at the exact second a buyer in that browser
      // completed a JazzCash purchase.
      'SCDynimacBridge',
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

// Run `fn` once the page has finished loading AND the browser reports idle
// time — i.e. after the visitor's first taps have had the main thread to
// themselves. Used for everything that is not needed to draw or use the page:
// analytics tags, error monitoring (components/Analytics.js,
// instrumentation-client.js). The idle timeout caps the wait on a page that
// never goes quiet; browsers without requestIdleCallback (older iOS Safari)
// get a plain delay after load instead.
export function runWhenIdle(fn, { timeout = 4000, fallbackDelay = 2000 } = {}) {
  if (typeof window === 'undefined') return;
  const schedule = () => {
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(() => fn(), { timeout });
    } else {
      setTimeout(fn, fallbackDelay);
    }
  };
  if (document.readyState === 'complete') schedule();
  else window.addEventListener('load', schedule, { once: true });
}

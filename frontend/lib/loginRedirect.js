// Sending a guest to /login and bringing them back where they were.
//
// Guests see the real Buy and Chat controls on a listing; using either one
// bounces them through /login?next=<where they were>, and every auth screen
// in that chain (login, register, verify-email, complete-profile) carries the
// param forward so they land back on the listing instead of home/dashboard.

export const NEXT_PARAM = 'next';

// Only same-site absolute paths survive. `//evil.com` and `/\evil.com` are
// treated as absolute URLs by browsers, so anything but a single leading
// slash followed by a normal character is dropped.
export function safeNextPath(next) {
  if (typeof next !== 'string') return null;
  if (!/^\/[^/\\]/.test(next)) return null;
  return next;
}

// Append ?next= to an auth path, skipping it when there is nothing worth
// coming back to.
export function withNext(path, next) {
  const safe = safeNextPath(next);
  if (!safe) return path;
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}${NEXT_PARAM}=${encodeURIComponent(safe)}`;
}

export function loginHref(next) {
  return withNext('/login', next);
}

// The page the visitor is on right now, ready to hand to loginHref().
export function currentPath() {
  if (typeof window === 'undefined') return null;
  return safeNextPath(`${window.location.pathname}${window.location.search}`);
}

// Read ?next= out of the current URL without useSearchParams — the auth pages
// are prerendered, and that hook would force them behind a Suspense boundary
// (which is what keeps their forms in the server HTML, and the CLS down).
export function readNextParam() {
  if (typeof window === 'undefined') return null;
  const value = new URLSearchParams(window.location.search).get(NEXT_PARAM);
  return safeNextPath(value);
}

// Where to send someone once they are signed in: their original destination
// if we have one, otherwise the usual landing page for their account.
export function postLoginPath(next, user) {
  return safeNextPath(next) || (user?.is_seller ? '/dashboard' : '/');
}

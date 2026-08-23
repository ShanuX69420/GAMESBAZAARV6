// First-touch acquisition capture.
//
// On the very first page load we stash where the visitor came from
// (document.referrer) and where they landed (path + query — UTM tags like
// ChatGPT's utm_source=chatgpt.com live in the query). The stash is
// write-once: client-side route changes and later visits never overwrite
// it. When an account gets created (register, Google sign-in, guest
// checkout) the stash rides along in the request body and the backend
// turns it into a permanent source label on the profile.

const STORAGE_KEY = 'gb_first_touch';

export function captureFirstTouch() {
  if (typeof window === 'undefined') return;
  try {
    if (localStorage.getItem(STORAGE_KEY)) return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      referrer: document.referrer || '',
      landing_page: `${location.pathname}${location.search}`,
      first_seen_at: new Date().toISOString(),
    }));
  } catch {
    // Private browsing / storage disabled — attribution stays unknown.
  }
}

export function getFirstTouch() {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data || typeof data !== 'object') return null;
    return data;
  } catch {
    return null;
  }
}

// Spread into an account-creating request body: {} when nothing was
// captured, so bodies never carry an explicit null.
export function attributionBody() {
  const firstTouch = getFirstTouch();
  return firstTouch ? { attribution: firstTouch } : {};
}

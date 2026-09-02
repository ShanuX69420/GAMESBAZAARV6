// Listing lifecycle, frontend half. The backend decides what a listing URL
// does once the listing stops selling (backend/core/listing_lifecycle.py):
//
//   active     normal page
//   paused     recently out of stock — same page, no buy button, siblings shown
//   gone       redirect (308) to the heir the backend named
//   unindexed  never crawled — plain 404
//
// The API answers 200 for all four (a 404 would leave a stale cached copy of
// the old page serving forever), so the page reads `lifecycle` and acts.
// Payloads cached before this shipped carry no `lifecycle`; those fall back
// on `status`.

function sitePath(value) {
  const path = String(value ?? '').trim();
  if (!path.startsWith('/') || path.startsWith('//')) return null;
  return path;
}

export function listingLifecycle(listing) {
  if (!listing || typeof listing !== 'object') {
    return { state: 'missing', redirectTo: null };
  }

  const info = listing.lifecycle && typeof listing.lifecycle === 'object'
    ? listing.lifecycle
    : null;

  switch (info?.state) {
    case 'active':
      return { state: 'active', redirectTo: null };
    case 'paused':
      return { state: 'paused', redirectTo: null };
    case 'gone': {
      const redirectTo = sitePath(info.redirect_to);
      // A "gone" with nowhere to go is a 404, never a redirect loop to "/".
      return redirectTo
        ? { state: 'gone', redirectTo }
        : { state: 'unindexed', redirectTo: null };
    }
    case 'unindexed':
      return { state: 'unindexed', redirectTo: null };
    default:
      break;
  }

  if (listing.status === 'retired') return { state: 'unindexed', redirectTo: null };
  if (listing.status && listing.status !== 'active') return { state: 'paused', redirectTo: null };
  return { state: 'active', redirectTo: null };
}

// True when the page should render but nothing can be bought.
export function listingIsOutOfStock(listing) {
  return listingLifecycle(listing).state === 'paused';
}

// Sibling options the backend picked for an out-of-stock page.
export function listingAlternatives(listing) {
  const list = listing?.lifecycle?.alternatives;
  if (!Array.isArray(list)) return [];
  return list.filter((alt) => alt && Number.isFinite(Number(alt.id)));
}

// Where "browse the rest" points on an out-of-stock page.
export function listingBrowsePath(listing) {
  return sitePath(listing?.lifecycle?.browse_path);
}

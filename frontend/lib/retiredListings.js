// Listing pages deleted by the catalog retirements (offline activation
// 2026-08-23, direct top-ups + six gift-card brands 2026-09-02). Listing ids
// are never reused, so an id in this map is gone for good; the page sends the
// visitor to the nearest live page instead of a 404. The map is keyed by
// destination so it stays reviewable — see lib/retiredRoutes.mjs for how the
// destinations were chosen.
import retiredByDestination from './retiredListings.json';

const DESTINATION_BY_ID = new Map();
for (const [destination, ids] of Object.entries(retiredByDestination)) {
  for (const id of ids) {
    DESTINATION_BY_ID.set(String(id), destination);
  }
}

export function retiredListingRedirect(id) {
  const key = String(id ?? '').trim();
  if (!key) return null;
  return DESTINATION_BY_ID.get(key) || null;
}

export function retiredListingCount() {
  return DESTINATION_BY_ID.size;
}

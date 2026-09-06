// Query-string params a game+category page applies after mount.
//
// The page itself is a static copy of its bare URL (2026-09-06 slow-click
// fix D): the server never sees the query, so the client reads it here and
// asks the API for the matching listings. These are the same three params
// the server used to read:
//   ?option=            a shared link to one denomination (offer-mode pages)
//   ?method= / ?region= ad landings from /keys — the backend maps them onto
//                       the page's real filters and echoes the result in
//                       applied_filters
// Returns null when there is nothing to apply, so the cached payload is
// shown as is without a second fetch.
export function landingParamsFromSearch(search) {
  const query = new URLSearchParams(String(search || ''));
  const option = String(query.get('option') || '').trim();
  const method = String(query.get('method') || '').trim();
  const region = String(query.get('region') || '').trim();
  if (!option && !method && !region) return null;
  return { option, method, region };
}

// Query-string params a section page (/keys, /accounts, …) applies after mount.
//
// The page itself is a static copy of its bare URL (2026-09-07, the section-page
// half of the 2026-09-06 slow-click work): the server never sees the query, so
// the client reads it here and asks the API for the matching games. These are
// the same three params the server used to read:
//   ?method= / ?region=  the Method and Region dropdowns — also how an ad can
//                        land straight on a filtered view
//   ?sort=               the Sort by dropdown
// Returns null when there is nothing to apply, so the cached payload is shown
// as is without a second fetch.
export function sectionParamsFromSearch(search) {
  const query = new URLSearchParams(String(search || ''));
  const method = String(query.get('method') || '').trim();
  const region = String(query.get('region') || '').trim();
  const sort = String(query.get('sort') || '').trim();
  if (!method && !region && !sort) return null;
  return { method, region, sort };
}

// The URL a selection should show. Only the dropdowns that are actually set
// appear, so the bare page and "reset filters" both land back on /keys and a
// filtered view stays shareable.
export function sectionUrl(basePath, { method, region, sort } = {}) {
  const params = new URLSearchParams();
  if (method) params.set('method', method);
  if (region) params.set('region', region);
  if (sort) params.set('sort', sort);
  const query = params.toString();
  return query ? `${basePath}?${query}` : basePath;
}

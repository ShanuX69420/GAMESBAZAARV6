function encodePathSegment(value) {
  return encodeURIComponent(String(value));
}

function normalizedApiBase(apiBase) {
  return String(apiBase || '').replace(/\/+$/, '');
}

export function buildGameCategoryListingUrl({
  apiBase,
  gameSlug,
  categorySlug,
  // An allow-listed region page (/games/<game>/<category>/<region>) reads
  // its own endpoint, which pins the Region filter server-side.
  regionSlug = '',
  limit,
  offset = 0,
  filters = {},
  instantOnly = false,
  search = '',
  ordering = '',
  option = '',
  method = '',
  region = '',
}) {
  const query = new URLSearchParams();

  if (limit !== undefined && limit !== null) {
    query.set('limit', String(limit));
  }
  if (offset !== undefined && offset !== null) {
    query.set('offset', String(offset));
  }
  if (option) {
    query.set('option', String(option));
  }
  // Ad-landing semantic filters (/keys carries them onto game links); the
  // backend maps them to this page's real filters and echoes applied_filters.
  if (method) {
    query.set('method', String(method));
  }
  if (region) {
    query.set('region', String(region));
  }

  Object.entries(filters)
    .filter(([, value]) => value)
    .forEach(([key, value]) => query.set(`filter_${key}`, value));

  if (instantOnly) {
    query.set('instant_delivery', 'true');
  }
  if (search) {
    query.set('search', search);
  }
  if (ordering) {
    query.set('ordering', ordering);
  }

  const queryString = query.toString();
  const regionSegment = regionSlug ? `${encodePathSegment(regionSlug)}/` : '';
  const path = `${normalizedApiBase(apiBase)}/api/games/${encodePathSegment(gameSlug)}/${encodePathSegment(categorySlug)}/${regionSegment}`;
  return queryString ? `${path}?${queryString}` : path;
}

export function buildSellerListingsPath({ gameSlug, categorySlug }) {
  return `/games/${encodePathSegment(gameSlug)}/${encodePathSegment(categorySlug)}`;
}

export function buildSellerProfilePath(username) {
  return `/seller/${encodePathSegment(username)}`;
}

/**
 * Renamed category pages answer at both the buyer-facing slug (e.g.
 * /games/roblox/robux) and the category's own slug (/games/roblox/currency):
 * the backend resolves either so old links keep working. Only the buyer-facing
 * URL is canonical. Returns the path to send the other one to, with the query
 * string preserved, or null when the request already uses the canonical slug
 * (or there is no data to decide with).
 */
export function canonicalCategoryPath({ gameSlug, requestedSlug, data, query, regionSlug = '' }) {
  const canonicalSlug = String(data?.category?.slug || '').trim();
  const requested = String(requestedSlug || '').trim();
  if (!canonicalSlug || !requested || canonicalSlug === requested) return null;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query || {})) {
    const values = Array.isArray(value) ? value : [value];
    for (const item of values) {
      if (item === undefined || item === null || item === '') continue;
      params.append(key, String(item));
    }
  }
  const search = params.toString();
  // A region page keeps its region segment; only the category slug changes.
  const regionSegment = regionSlug ? `/${encodeURIComponent(regionSlug)}` : '';
  return `/games/${encodeURIComponent(gameSlug)}/${encodeURIComponent(canonicalSlug)}${regionSegment}${search ? `?${search}` : ''}`;
}


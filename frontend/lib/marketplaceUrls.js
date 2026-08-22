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
  const path = `${normalizedApiBase(apiBase)}/api/games/${encodePathSegment(gameSlug)}/${encodePathSegment(categorySlug)}/`;
  return queryString ? `${path}?${queryString}` : path;
}

export function buildSellerListingsPath({ gameSlug, categorySlug }) {
  return `/games/${encodePathSegment(gameSlug)}/${encodePathSegment(categorySlug)}`;
}

export function buildSellerProfilePath(username) {
  return `/seller/${encodePathSegment(username)}`;
}

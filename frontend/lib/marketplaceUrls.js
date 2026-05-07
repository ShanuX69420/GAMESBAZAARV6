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
  onlineOnly = false,
  search = '',
  seller = '',
  ordering = '',
}) {
  const query = new URLSearchParams();

  if (limit !== undefined && limit !== null) {
    query.set('limit', String(limit));
  }
  if (offset !== undefined && offset !== null) {
    query.set('offset', String(offset));
  }

  Object.entries(filters)
    .filter(([, value]) => value)
    .forEach(([key, value]) => query.set(`filter_${key}`, value));

  if (instantOnly) {
    query.set('instant_delivery', 'true');
  }
  if (onlineOnly) {
    query.set('online_only', 'true');
  }
  if (search) {
    query.set('search', search);
  }
  if (seller) {
    query.set('seller', seller);
  }
  if (ordering) {
    query.set('ordering', ordering);
  }

  const queryString = query.toString();
  const path = `${normalizedApiBase(apiBase)}/api/games/${encodePathSegment(gameSlug)}/${encodePathSegment(categorySlug)}/`;
  return queryString ? `${path}?${queryString}` : path;
}

export function buildSellerListingsPath({ gameSlug, categorySlug, seller = '' }) {
  const query = seller ? `?${new URLSearchParams({ seller }).toString()}` : '';
  return `/games/${encodePathSegment(gameSlug)}/${encodePathSegment(categorySlug)}${query}`;
}

export function buildSellerProfilePath(username) {
  return `/seller/${encodePathSegment(username)}`;
}

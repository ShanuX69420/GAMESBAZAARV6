// Allow-listed region pages: /games/<game>/<category>/<region> is the brand
// page with its Region filter pinned to one option value (SEO fix #10).
// The backend says which regions a page has (`region_pages`, with stock
// counts) and, on a region page, which one this is (`region_page`). These
// helpers are the pure bits the page, the client component and the tests
// share.

export function regionPagePath({ gameSlug, categorySlug, region }) {
  return `/games/${encodeURIComponent(gameSlug)}/${encodeURIComponent(categorySlug)}/${encodeURIComponent(region)}`;
}

export function brandPagePath({ gameSlug, categorySlug }) {
  return `/games/${encodeURIComponent(gameSlug)}/${encodeURIComponent(categorySlug)}`;
}

// Region pages worth linking to: the ones with stock, like the sibling
// category tabs — an empty region page is noindexed and a dead end.
export function stockedRegionPages(regionPages) {
  return (regionPages || []).filter((page) => (page?.listing_count || 0) > 0);
}

// Where the Region dropdown sends a buyer who changes it ON a region page.
// The page cannot show another region (its URL is the region), so picking
// one navigates: to that region's own page when it is allow-listed, else to
// the brand page pre-filtered through the ?region= landing param (clearing
// the selection goes to the plain brand page).
export function regionSwitchTarget({ gameSlug, categorySlug, regionPages, value }) {
  const brand = brandPagePath({ gameSlug, categorySlug });
  const region = String(value || '').trim();
  if (!region) return brand;
  const page = (regionPages || []).find((candidate) => candidate?.region === region);
  if (page?.path) return page.path;
  return `${brand}?region=${encodeURIComponent(region)}`;
}

// Visible H1 on a region page: "PlayStation Gift Cards (USA)" — the region
// in brackets, the same way the option tiles name it ("10 USD (USA)").
export function regionPageHeading({ gameName, categoryName, regionLabel }) {
  return `${gameName} ${categoryName} (${regionLabel})`;
}

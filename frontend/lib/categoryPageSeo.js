// Server-side helpers shared by the game+category page and its allow-listed
// region pages (/games/<game>/<category>[/<region>]): the one API fetch both
// the page body and generateMetadata make (same URL + revalidate, so Next
// reuses one request), the slug-derived fallbacks for pages without
// hand-written copy, and the noindex rule for pages with nothing to buy.

import { API_BASE } from '@/lib/config';
import { buildGameCategoryListingUrl } from '@/lib/marketplaceUrls';
import { createPublicMetadata } from '@/lib/seo';
import { brandPagePath, regionPagePath } from '@/lib/regionPages';

export const LISTING_PAGE_SIZE = 48;
export const PUBLIC_CATEGORY_REVALIDATE_SECONDS = 120;

export function categoryPageApiUrl({ slug, categorySlug, regionSlug = '', option = '', method = '', region = '' }) {
  return buildGameCategoryListingUrl({
    apiBase: API_BASE,
    gameSlug: slug,
    categorySlug,
    regionSlug,
    limit: LISTING_PAGE_SIZE,
    offset: 0,
    option,
    method,
    region,
  });
}

export function fetchCategoryPage(url) {
  return fetch(url, { next: { revalidate: PUBLIC_CATEGORY_REVALIDATE_SECONDS } });
}

// What generateMetadata needs from the page payload. `null` when the API is
// unreachable (the page then keeps its generic title and stays indexable —
// a flaky backend must never noindex the catalogue), `{ notFound: true }`
// for a page that does not exist.
export async function fetchCategorySeoSummary(url) {
  const res = await fetchCategoryPage(url);
  if (res.status === 404) return { notFound: true };
  if (!res.ok) return null;
  const data = await res.json();
  return {
    listingCount: data?.listing_pagination?.count ?? data?.listings?.length ?? 0,
    // Region pages report the stock of their region; in offer mode the
    // listing count above only covers the selected denomination.
    regionListingCount: data?.region_listing_count,
    seoTitle: data?.seo_title || '',
    seoDescription: data?.seo_description || '',
    regionLabel: data?.region_page?.label || '',
    gameName: data?.game?.name || '',
    categoryName: data?.category?.name || '',
  };
}

export function titleFromSlug(value, fallback) {
  const text = String(value || '')
    .replace(/[-_+]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!text) return fallback;

  return text.replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

export function fallbackTitle(slug, categorySlug) {
  const gameName = titleFromSlug(slug, 'Game');
  const categoryName = titleFromSlug(categorySlug, 'Listings');
  return `${gameName} ${categoryName} Listings`;
}

export function fallbackDescription(slug, categorySlug) {
  const gameName = titleFromSlug(slug, 'Game');
  const categoryName = titleFromSlug(categorySlug, 'Listings');
  return `Browse ${gameName} ${categoryName} on GamesBazaar. Instant delivery, easy refunds, and prices in PKR.`;
}

export function fallbackRegionTitle(slug, categorySlug, regionSlug, seo) {
  const gameName = seo?.gameName || titleFromSlug(slug, 'Game');
  const categoryName = seo?.categoryName || titleFromSlug(categorySlug, 'Listings');
  const regionLabel = seo?.regionLabel || titleFromSlug(regionSlug, 'Region');
  return `${gameName} ${categoryName} ${regionLabel} in Pakistan`;
}

export function fallbackRegionDescription(slug, categorySlug, regionSlug, seo) {
  const gameName = seo?.gameName || titleFromSlug(slug, 'Game');
  const categoryName = seo?.categoryName || titleFromSlug(categorySlug, 'Listings');
  const regionLabel = seo?.regionLabel || titleFromSlug(regionSlug, 'Region');
  return `${regionLabel} region ${gameName} ${categoryName} at PKR prices on GamesBazaar. Pay with JazzCash, Easypaisa or bank transfer; codes delivered in minutes.`;
}

// Empty pages stay out of search engines until they have stock — hundreds of
// near-identical "no listings" pages read as thin content. The noindex lifts
// by itself once the first listing goes active. A page that does not exist
// is noindexed too (the body 404s; this keeps the metadata honest).
function robotsFor(seo, stock) {
  if (seo?.notFound) return { index: false, follow: false };
  if (stock === 0) return { index: false, follow: true };
  return undefined;
}

export function categoryPageMetadata({ slug, categorySlug, seo }) {
  return createPublicMetadata({
    title: seo?.seoTitle || fallbackTitle(slug, categorySlug),
    description: seo?.seoDescription || fallbackDescription(slug, categorySlug),
    path: brandPagePath({ gameSlug: slug, categorySlug }),
    robots: robotsFor(seo, seo?.listingCount),
    openGraph: {
      type: 'website',
    },
  });
}

export function regionPageMetadata({ slug, categorySlug, regionSlug, seo }) {
  return createPublicMetadata({
    title: seo?.seoTitle || fallbackRegionTitle(slug, categorySlug, regionSlug, seo),
    description: seo?.seoDescription || fallbackRegionDescription(slug, categorySlug, regionSlug, seo),
    path: regionPagePath({ gameSlug: slug, categorySlug, region: regionSlug }),
    robots: robotsFor(seo, seo?.regionListingCount),
    openGraph: {
      type: 'website',
    },
  });
}

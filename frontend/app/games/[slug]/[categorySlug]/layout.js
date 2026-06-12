import { Fragment, createElement } from 'react';
import JsonLd from '@/components/JsonLd';
import { API_BASE } from '@/lib/config';
import { buildGameCategoryListingUrl } from '@/lib/marketplaceUrls';
import {
  breadcrumbJsonLd,
  collectionPageJsonLd,
  createPublicMetadata,
} from '@/lib/seo';

// Mirrors the page's own data fetch (same URL + revalidate) so Next reuses
// the request instead of hitting the API twice.
const LISTING_PAGE_SIZE = 48;
const PUBLIC_CATEGORY_REVALIDATE_SECONDS = 120;

async function fetchCategoryListingCount(slug, categorySlug) {
  const url = buildGameCategoryListingUrl({
    apiBase: API_BASE,
    gameSlug: slug,
    categorySlug,
    limit: LISTING_PAGE_SIZE,
    offset: 0,
  });
  const res = await fetch(url, {
    next: { revalidate: PUBLIC_CATEGORY_REVALIDATE_SECONDS },
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data?.listing_pagination?.count ?? data?.listings?.length ?? 0;
}

function titleFromSlug(value, fallback) {
  const text = String(value || '')
    .replace(/[-_+]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!text) return fallback;

  return text.replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

export async function generateMetadata({ params }) {
  const { slug, categorySlug } = await params;
  const gameName = titleFromSlug(slug, 'Game');
  const categoryName = titleFromSlug(categorySlug, 'Listings');
  const title = `${gameName} ${categoryName} Listings`;
  const description = `Browse ${gameName} ${categoryName} listings on GamesBazaar. Compare prices from verified sellers with buyer protection.`;

  // Empty categories stay out of search engines until they have stock —
  // hundreds of near-identical "no listings" pages read as thin content.
  // The noindex lifts automatically once the first listing goes active.
  let listingCount = null;
  try {
    listingCount = await fetchCategoryListingCount(slug, categorySlug);
  } catch {
    listingCount = null;
  }

  return createPublicMetadata({
    title,
    description,
    path: `/games/${encodeURIComponent(slug)}/${encodeURIComponent(categorySlug)}`,
    robots: listingCount === 0 ? { index: false, follow: true } : undefined,
    openGraph: {
      type: 'website',
    },
  });
}

export default async function GameCategoryLayout({ children, params }) {
  const { slug, categorySlug } = await params;
  const gameName = titleFromSlug(slug, 'Game');
  const categoryName = titleFromSlug(categorySlug, 'Listings');
  const title = `${gameName} ${categoryName} Listings`;
  const description = `Browse ${gameName} ${categoryName} listings on GamesBazaar. Compare prices from verified sellers with buyer protection.`;
  const path = `/games/${encodeURIComponent(slug)}/${encodeURIComponent(categorySlug)}`;

  return createElement(
    Fragment,
    null,
    createElement(JsonLd, {
      data: [
        breadcrumbJsonLd([
          { name: 'Home', path: '/' },
          { name: 'All Games', path: '/games' },
          { name: gameName, path: `/games/${encodeURIComponent(slug)}` },
          { name: categoryName, path },
        ]),
        collectionPageJsonLd({ name: title, description, path }),
      ],
    }),
    children,
  );
}

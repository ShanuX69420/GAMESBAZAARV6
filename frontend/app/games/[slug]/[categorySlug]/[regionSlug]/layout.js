import { Fragment, createElement } from 'react';
import { notFound } from 'next/navigation';
import JsonLd from '@/components/JsonLd';
import { breadcrumbJsonLd, collectionPageJsonLd } from '@/lib/seo';
import {
  categoryPageApiUrl,
  fallbackRegionDescription,
  fallbackRegionTitle,
  fetchCategorySeoSummary,
  regionPageMetadata,
  titleFromSlug,
} from '@/lib/categoryPageSeo';
import { brandPagePath, regionPagePath } from '@/lib/regionPages';

// Metadata + JSON-LD for an allow-listed region page
// (/games/playstation/gift-cards/usa): its own priced title, self-canonical,
// Brand › Region breadcrumb, and a noindex while the region has no stock.
// No JSX here on purpose — the vitest suite imports this file.

export async function generateMetadata({ params }) {
  const { slug, categorySlug, regionSlug } = await params;

  let seo = null;
  try {
    seo = await fetchCategorySeoSummary(categoryPageApiUrl({ slug, categorySlug, regionSlug }));
  } catch {
    seo = null;
  }
  return regionPageMetadata({ slug, categorySlug, regionSlug, seo });
}

export default async function GameCategoryRegionLayout({ children, params }) {
  const { slug, categorySlug, regionSlug } = await params;

  let seo = null;
  try {
    seo = await fetchCategorySeoSummary(categoryPageApiUrl({ slug, categorySlug, regionSlug }));
  } catch {
    seo = null;
  }
  // A page the API does not know 404s from here, above the page's loading
  // boundary: a notFound() thrown inside the page arrives after the shell
  // has gone out with a 200, so the not-found screen showed with the wrong
  // status (and, now that the route is cached, would be stored that way).
  // An unreachable API (seo === null) is not a 404.
  if (seo?.notFound) notFound();

  const title = seo?.seoTitle || fallbackRegionTitle(slug, categorySlug, regionSlug, seo);
  const description = seo?.seoDescription || fallbackRegionDescription(slug, categorySlug, regionSlug, seo);
  const gameName = seo?.gameName || titleFromSlug(slug, 'Game');
  const categoryName = seo?.categoryName || titleFromSlug(categorySlug, 'Listings');
  const regionLabel = seo?.regionLabel || titleFromSlug(regionSlug, 'Region');
  const path = regionPagePath({ gameSlug: slug, categorySlug, region: regionSlug });
  const brandPath = brandPagePath({ gameSlug: slug, categorySlug });

  return createElement(
    Fragment,
    null,
    createElement(JsonLd, {
      data: [
        breadcrumbJsonLd([
          { name: 'Home', path: '/' },
          { name: 'All Games', path: '/games' },
          { name: gameName, path: `/games/${encodeURIComponent(slug)}` },
          { name: `${gameName} ${categoryName}`, path: brandPath },
          { name: regionLabel, path },
        ]),
        collectionPageJsonLd({ name: title, description, path }),
      ],
    }),
    children,
  );
}

import { Fragment, createElement } from 'react';
import JsonLd from '@/components/JsonLd';
import { breadcrumbJsonLd, collectionPageJsonLd } from '@/lib/seo';
import {
  categoryPageApiUrl,
  categoryPageMetadata,
  fallbackDescription,
  fallbackTitle,
  fetchCategorySeoSummary,
  titleFromSlug,
} from '@/lib/categoryPageSeo';
import { brandPagePath } from '@/lib/regionPages';

// The game+category page's metadata and JSON-LD. Lives in a layout inside
// the (brand) route group so it wraps ONLY the brand page: the allow-listed
// region pages under [regionSlug] carry their own title, canonical and
// breadcrumb. No JSX here on purpose — the vitest suite imports this file.

export async function generateMetadata({ params }) {
  const { slug, categorySlug } = await params;

  // Hand-written copy (seeded via seed_seo_text) wins; pages without it keep
  // the generic slug-derived title/description. Same URL + revalidate as
  // the page's own fetch, so Next reuses the request.
  let seo = null;
  try {
    seo = await fetchCategorySeoSummary(categoryPageApiUrl({ slug, categorySlug }));
  } catch {
    seo = null;
  }
  return categoryPageMetadata({ slug, categorySlug, seo });
}

export default async function GameCategoryLayout({ children, params }) {
  const { slug, categorySlug } = await params;

  let seo = null;
  try {
    seo = await fetchCategorySeoSummary(categoryPageApiUrl({ slug, categorySlug }));
  } catch {
    seo = null;
  }

  const title = seo?.seoTitle || fallbackTitle(slug, categorySlug);
  const description = seo?.seoDescription || fallbackDescription(slug, categorySlug);
  const gameName = seo?.gameName || titleFromSlug(slug, 'Game');
  const categoryName = seo?.categoryName || titleFromSlug(categorySlug, 'Listings');
  const path = brandPagePath({ gameSlug: slug, categorySlug });

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

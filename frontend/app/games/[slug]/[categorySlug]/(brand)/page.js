import { notFound, permanentRedirect } from 'next/navigation';
import CategorySeoText from '@/components/CategorySeoText';
import { canonicalCategoryPath } from '@/lib/marketplaceUrls';
import { categoryPageApiUrl, fetchCategoryPage } from '@/lib/categoryPageSeo';
import GameCategoryClient from '../GameCategoryClient';

// Metadata + JSON-LD live in ./layout.js (JSX-free so the test suite can
// import it); this file is the page body only.

// A cached page (2026-09-06 slow-click fix D). Nothing here reads the
// request — no searchParams, cookies or headers — so Next renders each
// game+category URL once, on its first visit, keeps the HTML and RSC
// payload, and refreshes them in the background every 2 minutes (the
// fetch's own revalidate, lib/categoryPageSeo.js). A click then costs one
// round trip for a stored payload instead of a Django call plus a full
// server render on the 1-vCPU box. The query string (?option= from a
// shared link, ?method=/?region= from a /keys ad landing) is applied by
// GameCategoryClient after mount.
//
// generateStaticParams must exist — even empty — for a dynamic segment to
// be cached at all: without it every request is a fresh server render.
export async function generateStaticParams() {
  return [];
}

async function fetchInitialCategoryData({ slug, categorySlug }) {
  const res = await fetchCategoryPage(categoryPageApiUrl({ slug, categorySlug }));
  if (res.status === 404) notFound();
  // Throw rather than render an empty shell: a failed render is never
  // stored, and a failed background refresh keeps serving the last good copy.
  if (!res.ok) throw new Error('Failed to fetch game category');
  return res.json();
}

export default async function GameCategoryPage({ params }) {
  const { slug, categorySlug } = await params;
  const initialData = await fetchInitialCategoryData({ slug, categorySlug });

  // A renamed page also answers at the category's own slug (old links keep
  // working), but only the buyer-facing URL should exist for search engines —
  // otherwise Google sees two self-canonical copies of the same page. The
  // query string is not carried over: the page never sees it (see above).
  const canonicalPath = canonicalCategoryPath({
    gameSlug: slug,
    requestedSlug: categorySlug,
    data: initialData,
  });
  if (canonicalPath) permanentRedirect(canonicalPath);

  return (
    <>
      <GameCategoryClient initialData={initialData} />
      <CategorySeoText text={initialData?.seo_body} />
    </>
  );
}

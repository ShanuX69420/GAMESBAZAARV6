import { notFound, permanentRedirect } from 'next/navigation';
import CategorySeoText from '@/components/CategorySeoText';
import { canonicalCategoryPath } from '@/lib/marketplaceUrls';
import { categoryPageApiUrl, fetchCategoryPage } from '@/lib/categoryPageSeo';
import GameCategoryClient from '../GameCategoryClient';

// An allow-listed region page: the game+category page with its Region
// filter pinned (/games/playstation/gift-cards/usa). The backend only
// answers for regions on the allow-list (CategoryRegionPage rows, seeded
// from seo_copy.json), so anything else is a plain 404 — never a thin
// auto-generated page for every region in the dropdown. Metadata + JSON-LD
// live in ./layout.js.

async function fetchInitialRegionData({ slug, categorySlug, regionSlug, option, method }) {
  const res = await fetchCategoryPage(
    categoryPageApiUrl({ slug, categorySlug, regionSlug, option, method }),
  );
  if (res.status === 404) notFound();
  if (!res.ok) throw new Error('Failed to fetch game category region');
  return res.json();
}

export default async function GameCategoryRegionPage({ params, searchParams }) {
  const { slug, categorySlug, regionSlug } = await params;
  const query = await searchParams;
  const option = String(query?.option || '');
  const method = String(query?.method || '');
  let initialData = null;

  try {
    initialData = await fetchInitialRegionData({ slug, categorySlug, regionSlug, option, method });
  } catch (error) {
    if (error?.digest?.startsWith?.('NEXT_HTTP_ERROR_FALLBACK;404')) {
      throw error;
    }
    console.error('Failed to fetch initial region page data:', error);
  }

  // Renamed categories: only the buyer-facing slug is canonical, here too.
  const canonicalPath = canonicalCategoryPath({
    gameSlug: slug,
    requestedSlug: categorySlug,
    data: initialData,
    query,
    regionSlug,
  });
  if (canonicalPath) permanentRedirect(canonicalPath);

  return (
    <>
      <GameCategoryClient initialData={initialData} />
      <CategorySeoText text={initialData?.seo_body} />
    </>
  );
}

import { notFound, permanentRedirect } from 'next/navigation';
import CategorySeoText from '@/components/CategorySeoText';
import { canonicalCategoryPath } from '@/lib/marketplaceUrls';
import { categoryPageApiUrl, fetchCategoryPage } from '@/lib/categoryPageSeo';
import GameCategoryClient from '../GameCategoryClient';

// Metadata + JSON-LD live in ./layout.js (JSX-free so the test suite can
// import it); this file is the page body only.

async function fetchInitialCategoryData({ slug, categorySlug, option, method, region }) {
  const res = await fetchCategoryPage(categoryPageApiUrl({ slug, categorySlug, option, method, region }));
  if (res.status === 404) notFound();
  if (!res.ok) throw new Error('Failed to fetch game category');
  return res.json();
}

export default async function GameCategoryPage({ params, searchParams }) {
  const { slug, categorySlug } = await params;
  const query = await searchParams;
  const option = String(query?.option || '');
  const method = String(query?.method || '');
  const region = String(query?.region || '');
  let initialData = null;

  try {
    initialData = await fetchInitialCategoryData({ slug, categorySlug, option, method, region });
  } catch (error) {
    if (error?.digest?.startsWith?.('NEXT_HTTP_ERROR_FALLBACK;404')) {
      throw error;
    }
    console.error('Failed to fetch initial category data:', error);
  }

  // A renamed page also answers at the category's own slug (old links keep
  // working), but only the buyer-facing URL should exist for search engines —
  // otherwise Google sees two self-canonical copies of the same page.
  const canonicalPath = canonicalCategoryPath({
    gameSlug: slug,
    requestedSlug: categorySlug,
    data: initialData,
    query,
  });
  if (canonicalPath) permanentRedirect(canonicalPath);

  return (
    <>
      <GameCategoryClient initialData={initialData} />
      <CategorySeoText text={initialData?.seo_body} />
    </>
  );
}

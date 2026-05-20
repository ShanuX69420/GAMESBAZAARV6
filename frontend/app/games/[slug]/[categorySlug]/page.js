import { notFound } from 'next/navigation';
import { API_BASE } from '@/lib/config';
import { buildGameCategoryListingUrl } from '@/lib/marketplaceUrls';
import GameCategoryClient from './GameCategoryClient';

const LISTING_PAGE_SIZE = 48;
const PUBLIC_CATEGORY_REVALIDATE_SECONDS = 120;

async function fetchInitialCategoryData({ slug, categorySlug, seller }) {
  const url = buildGameCategoryListingUrl({
    apiBase: API_BASE,
    gameSlug: slug,
    categorySlug,
    limit: LISTING_PAGE_SIZE,
    offset: 0,
    seller,
  });

  const res = await fetch(url, {
    next: { revalidate: PUBLIC_CATEGORY_REVALIDATE_SECONDS },
  });
  if (res.status === 404) notFound();
  if (!res.ok) throw new Error('Failed to fetch game category');
  return res.json();
}

export default async function GameCategoryPage({ params, searchParams }) {
  const { slug, categorySlug } = await params;
  const query = await searchParams;
  const seller = String(query?.seller || '');
  let initialData = null;

  try {
    initialData = await fetchInitialCategoryData({ slug, categorySlug, seller });
  } catch (error) {
    if (error?.digest?.startsWith?.('NEXT_HTTP_ERROR_FALLBACK;404')) {
      throw error;
    }
    console.error('Failed to fetch initial category data:', error);
  }

  return <GameCategoryClient initialData={initialData} initialSeller={seller} />;
}

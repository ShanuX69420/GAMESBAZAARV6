import { notFound } from 'next/navigation';
import { API_BASE } from '@/lib/config';
import { buildGameCategoryListingUrl } from '@/lib/marketplaceUrls';
import GameCategoryClient from './GameCategoryClient';

const LISTING_PAGE_SIZE = 48;
const PUBLIC_CATEGORY_REVALIDATE_SECONDS = 120;

async function fetchInitialCategoryData({ slug, categorySlug, seller, option }) {
  const url = buildGameCategoryListingUrl({
    apiBase: API_BASE,
    gameSlug: slug,
    categorySlug,
    limit: LISTING_PAGE_SIZE,
    offset: 0,
    seller,
    option,
  });

  const res = await fetch(url, {
    next: { revalidate: PUBLIC_CATEGORY_REVALIDATE_SECONDS },
  });
  if (res.status === 404) notFound();
  if (!res.ok) throw new Error('Failed to fetch game category');
  return res.json();
}

// Server-rendered so crawlers see the text without JS. Blank lines separate
// paragraphs; "## " lines become subheadings (matches the seo_body help text).
function CategorySeoText({ text }) {
  const blocks = String(text || '')
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean);
  if (!blocks.length) return null;

  return (
    <div className="container">
      <section className="category-seo-text">
        {blocks.map((block, index) => (
          block.startsWith('## ')
            ? <h2 key={index}>{block.slice(3).trim()}</h2>
            : <p key={index}>{block}</p>
        ))}
      </section>
    </div>
  );
}

export default async function GameCategoryPage({ params, searchParams }) {
  const { slug, categorySlug } = await params;
  const query = await searchParams;
  const seller = String(query?.seller || '');
  const option = String(query?.option || '');
  let initialData = null;

  try {
    initialData = await fetchInitialCategoryData({ slug, categorySlug, seller, option });
  } catch (error) {
    if (error?.digest?.startsWith?.('NEXT_HTTP_ERROR_FALLBACK;404')) {
      throw error;
    }
    console.error('Failed to fetch initial category data:', error);
  }

  return (
    <>
      <GameCategoryClient initialData={initialData} initialSeller={seller} />
      <CategorySeoText text={initialData?.seo_body} />
    </>
  );
}

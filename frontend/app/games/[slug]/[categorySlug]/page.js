import { notFound } from 'next/navigation';
import { API_BASE } from '@/lib/config';
import { buildGameCategoryListingUrl } from '@/lib/marketplaceUrls';
import GameCategoryClient from './GameCategoryClient';

const LISTING_PAGE_SIZE = 48;
const PUBLIC_CATEGORY_REVALIDATE_SECONDS = 120;

async function fetchInitialCategoryData({ slug, categorySlug, option, method, region }) {
  const url = buildGameCategoryListingUrl({
    apiBase: API_BASE,
    gameSlug: slug,
    categorySlug,
    limit: LISTING_PAGE_SIZE,
    offset: 0,
    option,
    method,
    region,
  });

  const res = await fetch(url, {
    next: { revalidate: PUBLIC_CATEGORY_REVALIDATE_SECONDS },
  });
  if (res.status === 404) notFound();
  if (!res.ok) throw new Error('Failed to fetch game category');
  return res.json();
}

// Server-rendered so crawlers see the text without JS. Blank lines separate
// paragraphs; "## " lines become subheadings and "### " sub-subheadings, e.g.
// FAQ questions (matches the seo_body help text).
function CategorySeoText({ text }) {
  const blocks = String(text || '')
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean);
  if (!blocks.length) return null;

  return (
    <div className="container">
      <section className="category-seo-text">
        {blocks.map((block, index) => {
          if (block.startsWith('### ')) {
            return <h3 key={index}>{block.slice(4).trim()}</h3>;
          }
          if (block.startsWith('## ')) {
            return <h2 key={index}>{block.slice(3).trim()}</h2>;
          }
          return <p key={index}>{block}</p>;
        })}
      </section>
    </div>
  );
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

  return (
    <>
      <GameCategoryClient initialData={initialData} />
      <CategorySeoText text={initialData?.seo_body} />
    </>
  );
}

import { notFound, permanentRedirect } from 'next/navigation';
import { API_BASE } from '@/lib/config';
import { buildGameCategoryListingUrl, canonicalCategoryPath } from '@/lib/marketplaceUrls';
import JsonLd from '@/components/JsonLd';
import SeoTextBlocks from '@/components/SeoTextBlocks';
import { faqPageJsonLd } from '@/lib/seo';
import { extractSeoFaq, splitSeoBlocks } from '@/lib/seoText';
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

// Server-rendered so crawlers see the text without JS. Copy conventions
// (paragraphs, "## " headings, [text](/path) links) live in lib/seoText.js.
// The FAQPage JSON-LD is built from the same blocks the section renders
// ("### " question + the paragraph under it), so the markup can never claim
// a question or answer the visible page doesn't show.
function CategorySeoText({ text }) {
  const blocks = splitSeoBlocks(text);
  if (!blocks.length) return null;
  const faq = extractSeoFaq(blocks);

  return (
    <div className="container">
      {faq.length > 0 && <JsonLd data={faqPageJsonLd([{ questions: faq }])} />}
      <section className="category-seo-text">
        <SeoTextBlocks blocks={blocks} />
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

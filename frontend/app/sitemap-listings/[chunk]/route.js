import { getSiteUrl } from '@/lib/seo';
import {
  LISTING_SITEMAP_CHUNK_SIZE,
  fetchListingSitemapPage,
  urlSetResponse,
} from '@/lib/sitemap';

// One chunk of listing URLs, e.g. /sitemap-listings/0.xml.
function parseChunk(value) {
  const match = /^(\d+)\.xml$/.exec(String(value || ''));
  return match ? Number(match[1]) : null;
}

export async function GET(request, { params }) {
  const { chunk } = await params;
  const index = parseChunk(chunk);
  if (index === null) {
    return new Response('Not Found', { status: 404 });
  }

  let results = [];
  try {
    ({ results } = await fetchListingSitemapPage({
      limit: LISTING_SITEMAP_CHUNK_SIZE,
      offset: index * LISTING_SITEMAP_CHUNK_SIZE,
    }));
  } catch {
    // An empty <urlset> is valid. Serving one beats a 5xx, which makes Search
    // Console drop the whole sitemap rather than retry it.
    results = [];
  }

  const siteUrl = getSiteUrl();
  return urlSetResponse(results.map((listing) => ({
    loc: `${siteUrl}/listing/${listing.id}`,
    lastModified: listing.updated_at,
  })));
}

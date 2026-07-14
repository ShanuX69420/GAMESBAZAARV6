import {
  fetchActiveListingCount,
  listingSitemapChunkCount,
  listingSitemapChunkUrl,
  sitemapIndexResponse,
} from '@/lib/sitemap';

// Sitemap index for listing pages. The chunk count is read from the live
// listing total on each request, so new listings — and new sellers — get
// crawled without anyone touching this file or redeploying.
export async function GET() {
  let chunks = 0;
  try {
    chunks = listingSitemapChunkCount(await fetchActiveListingCount());
  } catch {
    chunks = 0;
  }

  // Always advertise the first chunk. If the feed is briefly down, Google gets
  // a valid index pointing at an empty (but parseable) sitemap instead of a
  // document with no children, which it reports as an error.
  return sitemapIndexResponse(
    Array.from({ length: Math.max(chunks, 1) }, (_, chunk) => listingSitemapChunkUrl(chunk)),
  );
}

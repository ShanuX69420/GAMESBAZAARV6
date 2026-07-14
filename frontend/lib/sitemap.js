import { API_BASE } from '@/lib/config';
import { getSiteUrl } from '@/lib/seo';

// Google rejects a sitemap file with more than 50,000 URLs. We chunk at half
// that so the catalogue can keep growing without any single file overflowing —
// the number of chunks is derived from the live listing count on every request,
// so no cap has to be picked up front and no redeploy is needed as sellers add
// listings.
export const LISTING_SITEMAP_CHUNK_SIZE = 25000;
export const LISTING_SITEMAP_REVALIDATE_SECONDS = 3600;

export async function fetchListingSitemapPage({ limit, offset }) {
  const url = `${API_BASE}/api/sitemap/listings/?limit=${limit}&offset=${offset}`;
  const res = await fetch(url, {
    next: { revalidate: LISTING_SITEMAP_REVALIDATE_SECONDS },
  });
  if (!res.ok) throw new Error(`Sitemap listing feed returned HTTP ${res.status}`);

  const data = await res.json();
  return {
    count: Number(data?.count) || 0,
    results: Array.isArray(data?.results) ? data.results : [],
  };
}

export async function fetchActiveListingCount() {
  // limit=1 is the cheapest way to read the total — we only want `count`.
  const { count } = await fetchListingSitemapPage({ limit: 1, offset: 0 });
  return count;
}

export function listingSitemapChunkCount(total) {
  const count = Number(total) || 0;
  if (count <= 0) return 0;
  return Math.ceil(count / LISTING_SITEMAP_CHUNK_SIZE);
}

export function listingSitemapChunkUrl(chunk) {
  return `${getSiteUrl()}/sitemap-listings/${chunk}.xml`;
}

export function listingSitemapIndexUrl() {
  return `${getSiteUrl()}/sitemap-listings.xml`;
}

function xmlResponse(body) {
  return new Response(`<?xml version="1.0" encoding="UTF-8"?>\n${body}\n`, {
    headers: {
      'Content-Type': 'application/xml; charset=utf-8',
      'Cache-Control': `public, max-age=${LISTING_SITEMAP_REVALIDATE_SECONDS}`,
    },
  });
}

export function sitemapIndexResponse(chunkUrls) {
  const entries = chunkUrls
    .map((url) => `  <sitemap>\n    <loc>${url}</loc>\n  </sitemap>`)
    .join('\n');

  return xmlResponse(
    `<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${entries}\n</sitemapindex>`,
  );
}

export function urlSetResponse(entries) {
  const urls = entries
    .map(({ loc, lastModified }) => {
      const lastmod = lastModified ? `\n    <lastmod>${lastModified}</lastmod>` : '';
      return `  <url>\n    <loc>${loc}</loc>${lastmod}\n    <changefreq>daily</changefreq>\n    <priority>0.6</priority>\n  </url>`;
    })
    .join('\n');

  return xmlResponse(
    `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>`,
  );
}

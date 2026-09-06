import { getSiteUrl } from '@/lib/seo';
import { listingSitemapIndexUrl } from '@/lib/sitemap';

export default function robots() {
  const siteUrl = getSiteUrl();
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        disallow: [
          '/inbox',
          '/inbox/',
          '/orders',
          '/orders/',
          '/sales',
          '/sales/',
          '/my-listings',
          '/my-listings/',
          '/wallet',
          '/wallet/',
          '/dashboard',
          '/dashboard/',
          '/settings',
          '/settings/',
          '/notifications',
          '/notifications/',
          '/order',
          '/order/',
        ],
      },
      // Crawlers that send no visitors but were ~7% of all requests on the
      // single-CPU server (2026-09-06 slow-click diagnosis). Google and Bing
      // rules stay exactly as they are.
      { userAgent: 'MJ12bot', disallow: '/' },
      { userAgent: 'PetalBot', disallow: '/' },
    ],
    // Static + game-category pages in the first, every listing page in the
    // second (an index that fans out into as many chunks as the catalogue needs).
    sitemap: [`${siteUrl}/sitemap.xml`, listingSitemapIndexUrl()],
  };
}

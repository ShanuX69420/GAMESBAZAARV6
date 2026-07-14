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
    ],
    // Static + game-category pages in the first, every listing page in the
    // second (an index that fans out into as many chunks as the catalogue needs).
    sitemap: [`${siteUrl}/sitemap.xml`, listingSitemapIndexUrl()],
  };
}

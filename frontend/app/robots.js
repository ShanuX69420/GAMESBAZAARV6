import { getSiteUrl } from '@/lib/seo';

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
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}

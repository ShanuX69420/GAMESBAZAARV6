import { afterEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const testDir = dirname(fileURLToPath(import.meta.url));

async function importFresh(modulePath) {
  vi.resetModules();
  return import(modulePath);
}

function readProjectFile(path) {
  return readFileSync(join(testDir, '..', path), 'utf8');
}

describe('SEO route metadata', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it('keeps private account areas out of robots while pointing at the configured sitemap', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');

    const { default: robots } = await importFresh('../app/robots.js');
    const config = robots();

    expect(config.sitemap).toBe('https://www.gamesbazaar.pk/sitemap.xml');
    expect(config.rules).toEqual([
      expect.objectContaining({
        userAgent: '*',
        allow: '/',
        disallow: expect.arrayContaining([
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
        ]),
      }),
    ]);
  });

  it('builds sitemap entries for static pages, games, and game categories', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue([
        {
          slug: 'valorant',
          categories: [
            { category: { slug: 'accounts' } },
            { category: { slug: 'boosting' } },
          ],
        },
      ]),
    }));

    const { default: sitemap } = await importFresh('../app/sitemap.js');
    const entries = await sitemap();

    expect(fetch).toHaveBeenCalledWith(
      'https://api.gamesbazaar.pk/api/games/',
      { next: { revalidate: 3600 } }
    );
    expect(entries).toEqual(expect.arrayContaining([
      expect.objectContaining({ url: 'https://www.gamesbazaar.pk', priority: 1.0 }),
      expect.objectContaining({ url: 'https://www.gamesbazaar.pk/games', priority: 0.9 }),
      expect.objectContaining({ url: 'https://www.gamesbazaar.pk/games/valorant', priority: 0.8 }),
      expect.objectContaining({ url: 'https://www.gamesbazaar.pk/games/valorant/accounts', priority: 0.7 }),
      expect.objectContaining({ url: 'https://www.gamesbazaar.pk/games/valorant/boosting', priority: 0.7 }),
    ]));
  });

  it('returns a static-only sitemap when the games API is unavailable', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')));

    const { default: sitemap } = await importFresh('../app/sitemap.js');
    const entries = await sitemap();

    expect(entries.map((entry) => entry.url)).toEqual([
      'https://www.gamesbazaar.pk',
      'https://www.gamesbazaar.pk/games',
      'https://www.gamesbazaar.pk/login',
      'https://www.gamesbazaar.pk/register',
      'https://www.gamesbazaar.pk/support',
      'https://www.gamesbazaar.pk/privacy-policy',
      'https://www.gamesbazaar.pk/terms-of-service',
    ]);
  });

  it('generates listing metadata from route params without an extra API request', async () => {
    vi.stubGlobal('fetch', vi.fn());

    const { generateMetadata } = await importFresh('../app/listing/[id]/layout.js');
    const metadata = await generateMetadata({ params: Promise.resolve({ id: 'GB-123' }) });

    expect(fetch).not.toHaveBeenCalled();
    expect(metadata).toMatchObject({
      title: 'Listing GB-123',
      description: 'View this GamesBazaar listing with secure checkout, buyer protection, and seller chat.',
      openGraph: {
        title: metadata.title,
        type: 'website',
        siteName: 'GamesBazaar',
      },
    });
  });

  it('does not force static/client-rendered shells dynamic for CSP', () => {
    const nonceOnlyDynamicPaths = [
      'app/not-found.js',
      'app/page.js',
      'app/games/page.js',
      'app/login/layout.js',
      'app/register/layout.js',
      'app/forgot-password/layout.js',
      'app/support/layout.js',
      'app/seller/apply/layout.js',
      'app/dashboard/layout.js',
      'app/inbox/layout.js',
      'app/my-listings/layout.js',
      'app/notifications/layout.js',
      'app/orders/layout.js',
      'app/sales/layout.js',
      'app/settings/layout.js',
      'app/wallet/layout.js',
    ];

    for (const path of nonceOnlyDynamicPaths) {
      expect(readProjectFile(path)).not.toContain("force-dynamic");
    }
  });

  it('marks authenticated account pages as noindex', async () => {
    const privateLayoutPaths = [
      '../app/dashboard/layout.js',
      '../app/inbox/layout.js',
      '../app/my-listings/layout.js',
      '../app/notifications/layout.js',
      '../app/order/[id]/layout.js',
      '../app/orders/layout.js',
      '../app/sales/layout.js',
      '../app/settings/layout.js',
      '../app/wallet/layout.js',
    ];

    for (const layoutPath of privateLayoutPaths) {
      const { metadata } = await importFresh(layoutPath);
      expect(metadata.robots).toMatchObject({
        index: false,
        follow: false,
        noarchive: true,
        nosnippet: true,
      });
    }
  });

  it('generates seller metadata from route params without an extra API request', async () => {
    vi.stubGlobal('fetch', vi.fn());

    const { generateMetadata } = await importFresh('../app/seller/[username]/layout.js');
    const metadata = await generateMetadata({ params: Promise.resolve({ username: 'seller+pk' }) });

    expect(fetch).not.toHaveBeenCalled();
    expect(metadata.title).toBe('seller+pk Seller Profile');
    expect(metadata.description).toContain("seller+pk's seller profile");
    expect(metadata.openGraph).toMatchObject({
      type: 'profile',
      siteName: 'GamesBazaar',
    });
  });

  it('generates game category metadata from route params without an extra API request', async () => {
    vi.stubGlobal('fetch', vi.fn());

    const { generateMetadata } = await importFresh('../app/games/[slug]/[categorySlug]/layout.js');
    const metadata = await generateMetadata({
      params: Promise.resolve({ slug: 'pubg mobile', categorySlug: 'accounts & boosts' }),
    });

    expect(fetch).not.toHaveBeenCalled();
    expect(metadata).toMatchObject({
      title: 'Pubg Mobile Accounts & Boosts Listings',
      description: 'Browse Pubg Mobile Accounts & Boosts listings on GamesBazaar. Compare prices from verified sellers with buyer protection.',
      openGraph: {
        title: metadata.title,
        type: 'website',
        siteName: 'GamesBazaar',
      },
    });
  });
});

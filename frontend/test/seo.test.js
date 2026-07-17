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

    expect(config.sitemap).toEqual([
      'https://www.gamesbazaar.pk/sitemap.xml',
      'https://www.gamesbazaar.pk/sitemap-listings.xml',
    ]);
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
            { category: { slug: 'accounts' }, listing_count: 5 },
            { category: { slug: 'boosting' }, listing_count: 1 },
            { category: { slug: 'gift-cards' }, listing_count: 0 },
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
      expect.objectContaining({ url: 'https://www.gamesbazaar.pk/games/valorant/accounts', priority: 0.7 }),
      expect.objectContaining({ url: 'https://www.gamesbazaar.pk/games/valorant/boosting', priority: 0.7 }),
    ]));
    // Empty categories are noindexed, so they stay out of the sitemap too.
    expect(entries).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ url: 'https://www.gamesbazaar.pk/games/valorant/gift-cards' }),
    ]));
    expect(entries).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ url: 'https://www.gamesbazaar.pk/games/valorant' }),
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

  it('looks up category slugs for sitemap games when the list endpoint only returns counts', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue([
          { slug: 'valorant', category_count: 1 },
        ]),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          slug: 'valorant',
          categories: [
            { category: { slug: 'accounts' }, listing_count: 2 },
          ],
        }),
      }));

    const { default: sitemap } = await importFresh('../app/sitemap.js');
    const entries = await sitemap();

    expect(fetch).toHaveBeenCalledWith(
      'https://api.gamesbazaar.pk/api/games/valorant/',
      { next: { revalidate: 3600 } }
    );
    expect(entries).toEqual(expect.arrayContaining([
      expect.objectContaining({ url: 'https://www.gamesbazaar.pk/games/valorant/accounts' }),
    ]));
    expect(entries).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ url: 'https://www.gamesbazaar.pk/games/valorant' }),
    ]));
  });

  it('fans the listing sitemap index out into one chunk per 25k listings', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ count: 60000, results: [] }),
    }));

    const { GET } = await importFresh('../app/sitemap-listings.xml/route.js');
    const xml = await (await GET()).text();

    // 60,000 listings -> ceil(60000 / 25000) = 3 chunks, with no cap to raise.
    expect(xml).toContain('<loc>https://www.gamesbazaar.pk/sitemap-listings/0.xml</loc>');
    expect(xml).toContain('<loc>https://www.gamesbazaar.pk/sitemap-listings/1.xml</loc>');
    expect(xml).toContain('<loc>https://www.gamesbazaar.pk/sitemap-listings/2.xml</loc>');
    expect(xml).not.toContain('sitemap-listings/3.xml');
  });

  it('still serves a valid listing sitemap index when the feed is down', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')));

    const { GET } = await importFresh('../app/sitemap-listings.xml/route.js');
    const response = await GET();
    const xml = await response.text();

    expect(response.status).toBe(200);
    expect(xml).toContain('<sitemapindex');
    expect(xml).toContain('<loc>https://www.gamesbazaar.pk/sitemap-listings/0.xml</loc>');
  });

  it('lists active listing URLs with lastmod in a sitemap chunk', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        count: 30000,
        results: [
          { id: 19890, updated_at: '2026-07-13T10:00:00+00:00' },
          { id: 19891, updated_at: '2026-07-13T11:00:00+00:00' },
        ],
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { GET } = await importFresh('../app/sitemap-listings/[chunk]/route.js');
    const response = await GET({}, { params: Promise.resolve({ chunk: '1.xml' }) });
    const xml = await response.text();

    // Chunk 1 must page past the first 25,000 listings.
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.gamesbazaar.pk/api/sitemap/listings/?limit=25000&offset=25000',
      { next: { revalidate: 3600 } },
    );
    expect(response.headers.get('Content-Type')).toContain('application/xml');
    expect(xml).toContain('<loc>https://www.gamesbazaar.pk/listing/19890</loc>');
    expect(xml).toContain('<lastmod>2026-07-13T11:00:00+00:00</lastmod>');
  });

  it('404s a malformed sitemap chunk and never 5xxes on a feed failure', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')));

    const { GET } = await importFresh('../app/sitemap-listings/[chunk]/route.js');

    const bad = await GET({}, { params: Promise.resolve({ chunk: 'not-a-chunk' }) });
    expect(bad.status).toBe(404);

    const down = await GET({}, { params: Promise.resolve({ chunk: '0.xml' }) });
    expect(down.status).toBe(200);
    expect(await down.text()).toContain('<urlset');
  });

  it('generates rich listing metadata from public listing data', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        title: 'Rare Valorant Account',
        price: '12500',
        game_name: 'Valorant',
        category_name: 'Accounts',
        seller_name: 'sellerpk',
        buyer_protection_enabled: true,
        filter_display: {
          Platform: 'PC',
        },
      }),
    }));

    const { generateMetadata } = await importFresh('../app/listing/[id]/layout.js');
    const metadata = await generateMetadata({ params: Promise.resolve({ id: 'GB-123' }) });

    expect(fetch).toHaveBeenCalledWith(
      'https://api.gamesbazaar.pk/api/listings/GB-123/',
      { next: { revalidate: 120 } }
    );
    expect(metadata).toMatchObject({
      title: 'Rare Valorant Account - PKR 12,500',
      alternates: {
        canonical: '/listing/GB-123',
      },
      openGraph: {
        title: metadata.title,
        url: '/listing/GB-123',
        type: 'website',
        siteName: 'GamesBazaar',
      },
      twitter: {
        card: 'summary_large_image',
      },
    });
    expect(metadata.description).toContain('Valorant PC Accounts listing sold by sellerpk');
  });

  it('wires per-listing reviews into the listing page Product JSON-LD', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        title: 'Rare Valorant Account',
        price: '12500',
        game_name: 'Valorant',
        category_name: 'Accounts',
        seller_name: 'sellerpk',
        status: 'active',
        listing_reviews: {
          average: 4.5,
          count: 2,
          recent: [
            {
              rating: 5,
              comment: 'Fast delivery',
              reviewer_name: 'buyer1',
              created_at: '2026-07-01T10:00:00+00:00',
            },
            {
              rating: 4,
              comment: '',
              reviewer_name: 'buyer2',
              created_at: '2026-06-20T10:00:00+00:00',
            },
          ],
        },
      }),
    }));

    const { default: ListingLayout } = await importFresh('../app/listing/[id]/layout.js');
    const element = await ListingLayout({
      children: null,
      params: Promise.resolve({ id: 'GB-123' }),
    });
    const data = element.props.children[0].props.data;

    expect(data.aggregateRating).toMatchObject({ ratingValue: 4.5, reviewCount: 2 });
    expect(data.review).toHaveLength(2);
    expect(data.review[0].author).toEqual({ '@type': 'Person', name: 'buyer1' });
    // ISO datetime from the API is trimmed to the date Google expects.
    expect(data.review[0].datePublished).toBe('2026-07-01');
    expect(data.review[1]).not.toHaveProperty('reviewBody');
  });

  it('emits the Product fields Google requires for merchant listings', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');

    const { productJsonLd } = await importFresh('../lib/seo.js');
    const data = productJsonLd({
      name: 'Rare Valorant Account',
      path: '/listing/GB-123',
      sku: 'GB-123',
      brand: 'Valorant',
      price: '12500.00',
      sellerName: 'sellerpk',
    });

    // Without an image Google marks the whole item invalid.
    expect(data.image).toBe('https://www.gamesbazaar.pk/opengraph-image');
    expect(data.brand).toEqual({ '@type': 'Brand', name: 'Valorant' });
    expect(data.offers.hasMerchantReturnPolicy).toMatchObject({
      '@type': 'MerchantReturnPolicy',
      applicableCountry: 'PK',
      returnPolicyCategory: 'https://schema.org/MerchantReturnNotPermitted',
    });
    expect(data.offers.shippingDetails).toMatchObject({
      '@type': 'OfferShippingDetails',
      shippingRate: { value: 0, currency: 'PKR' },
      shippingDestination: { addressCountry: 'PK' },
    });
  });

  it('emits aggregateRating and review when the listing has reviews', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');

    const { productJsonLd } = await importFresh('../lib/seo.js');
    const data = productJsonLd({
      name: 'Rare Valorant Account',
      path: '/listing/GB-123',
      price: '12500.00',
      aggregateRating: { value: 4.5, count: 2 },
      reviews: [
        { rating: 5, author: 'buyer1', body: 'Fast delivery', date: '2026-07-01' },
        { rating: 4, author: '', body: '', date: '' },
      ],
    });

    expect(data.aggregateRating).toEqual({
      '@type': 'AggregateRating',
      ratingValue: 4.5,
      reviewCount: 2,
      bestRating: 5,
      worstRating: 1,
    });
    expect(data.review).toHaveLength(2);
    expect(data.review[0]).toEqual({
      '@type': 'Review',
      reviewRating: { '@type': 'Rating', ratingValue: 5, bestRating: 5, worstRating: 1 },
      author: { '@type': 'Person', name: 'buyer1' },
      datePublished: '2026-07-01',
      reviewBody: 'Fast delivery',
    });
    // Empty author/body/date fall back or drop out rather than emitting
    // blank fields Google would flag.
    expect(data.review[1]).toEqual({
      '@type': 'Review',
      reviewRating: { '@type': 'Rating', ratingValue: 4, bestRating: 5, worstRating: 1 },
      author: { '@type': 'Person', name: 'GamesBazaar buyer' },
    });
  });

  it('omits aggregateRating and review entirely for unreviewed listings', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');

    const { productJsonLd } = await importFresh('../lib/seo.js');
    const data = productJsonLd({
      name: 'Rare Valorant Account',
      path: '/listing/GB-123',
      price: '12500.00',
      aggregateRating: null,
      reviews: [],
    });

    // A zero-count AggregateRating is invalid markup — the keys must be absent.
    expect(data).not.toHaveProperty('aggregateRating');
    expect(data).not.toHaveProperty('review');
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

  it('generates game category metadata and keeps stocked categories indexable', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ listing_pagination: { count: 12 } }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { generateMetadata } = await importFresh('../app/games/[slug]/[categorySlug]/layout.js');
    const metadata = await generateMetadata({
      params: Promise.resolve({ slug: 'pubg mobile', categorySlug: 'accounts & boosts' }),
    });

    // Reuses the page's own data request (same URL + revalidate).
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.gamesbazaar.pk/api/games/pubg%20mobile/accounts%20%26%20boosts/?limit=48&offset=0',
      { next: { revalidate: 120 } }
    );
    expect(metadata).toMatchObject({
      title: 'Pubg Mobile Accounts & Boosts Listings',
      description: 'Browse Pubg Mobile Accounts & Boosts listings on GamesBazaar. Compare prices from verified sellers with buyer protection.',
      openGraph: {
        title: metadata.title,
        type: 'website',
        siteName: 'GamesBazaar',
      },
    });
    expect(metadata.robots).toBeUndefined();
  });

  it('noindexes game category pages until they have active listings', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ listing_pagination: { count: 0 }, listings: [] }),
    }));

    const { generateMetadata } = await importFresh('../app/games/[slug]/[categorySlug]/layout.js');
    const metadata = await generateMetadata({
      params: Promise.resolve({ slug: 'pubg-mobile', categorySlug: 'gift-cards' }),
    });

    expect(metadata.robots).toEqual({ index: false, follow: true });
  });

  it('keeps category pages indexable when the listing count lookup fails', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')));

    const { generateMetadata } = await importFresh('../app/games/[slug]/[categorySlug]/layout.js');
    const metadata = await generateMetadata({
      params: Promise.resolve({ slug: 'pubg-mobile', categorySlug: 'accounts' }),
    });

    expect(metadata.robots).toBeUndefined();
  });
});

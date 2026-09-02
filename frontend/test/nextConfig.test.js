import { afterEach, describe, expect, it, vi } from 'vitest';

async function importFreshNextConfig() {
  vi.resetModules();
  return import('../next.config.mjs');
}

describe('Next configuration', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('allows configured API, site, and media hosts for optimized images', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk');
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk');
    vi.stubEnv(
      'NEXT_PUBLIC_IMAGE_HOSTS',
      'cdn.gamesbazaar.pk,https://media.gamesbazaar.pk:8443,ftp://ignored.invalid,api.gamesbazaar.pk'
    );

    const { default: nextConfig } = await importFreshNextConfig();

    expect(nextConfig.images.formats).toEqual(['image/webp']);
    expect(nextConfig.images.dangerouslyAllowLocalIP).toBe(true);
    expect(nextConfig.images.remotePatterns).toEqual(expect.arrayContaining([
      { protocol: 'https', hostname: 'api.gamesbazaar.pk' },
      { protocol: 'https', hostname: 'www.gamesbazaar.pk' },
      { protocol: 'https', hostname: 'cdn.gamesbazaar.pk' },
      { protocol: 'https', hostname: 'media.gamesbazaar.pk', port: '8443' },
      { protocol: 'http', hostname: 'localhost' },
      { protocol: 'http', hostname: '127.0.0.1' },
    ]));
    expect(
      nextConfig.images.remotePatterns.filter(
        (pattern) => pattern.hostname === 'api.gamesbazaar.pk'
      )
    ).toHaveLength(1);
    expect(
      nextConfig.images.remotePatterns.some(
        (pattern) => pattern.hostname === 'ignored.invalid'
      )
    ).toBe(false);
  });

  it('does not add localhost image patterns for production builds', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('NEXT_PUBLIC_IMAGE_HOSTS', 'cdn.gamesbazaar.pk');

    const { default: nextConfig } = await importFreshNextConfig();

    expect(nextConfig.images.remotePatterns).toEqual([
      { protocol: 'https', hostname: 'cdn.gamesbazaar.pk' },
    ]);
    expect(nextConfig.images.dangerouslyAllowLocalIP).toBe(false);
  });

  it('allows local image optimization for explicit local production builds', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('LOCAL_PRODUCTION_BUILD', '1');
    vi.stubEnv('NEXT_PUBLIC_IMAGE_HOSTS', 'localhost:8000');

    const { default: nextConfig } = await importFreshNextConfig();

    expect(nextConfig.images.dangerouslyAllowLocalIP).toBe(true);
  });

  it('leaves runtime security headers to proxy', async () => {
    vi.stubEnv('NODE_ENV', 'production');

    const { default: nextConfig } = await importFreshNextConfig();
    const headers = await nextConfig.headers();

    expect(nextConfig.poweredByHeader).toBe(false);
    expect(headers).not.toEqual(expect.arrayContaining([
      expect.objectContaining({
        headers: expect.arrayContaining([
          expect.objectContaining({ key: 'Content-Security-Policy' }),
        ]),
      }),
    ]));
  });

  it('sets stronger cache headers for the web app manifest and icons', async () => {
    const { default: nextConfig } = await importFreshNextConfig();

    await expect(nextConfig.headers()).resolves.toEqual([
      {
        source: '/manifest.json',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800',
          },
        ],
      },
      {
        source: '/icons/:path*',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=2592000, stale-while-revalidate=604800',
          },
        ],
      },
      {
        source: '/apple-touch-icon.png',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=2592000, stale-while-revalidate=604800',
          },
        ],
      },
      {
        source: '/favicon.ico',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=2592000, stale-while-revalidate=604800',
          },
        ],
      },
    ]);
  });

  it('redirects retired catalog pages to their nearest live page', async () => {
    const { default: nextConfig } = await importFreshNextConfig();
    const redirects = await nextConfig.redirects();
    const byPath = Object.fromEntries(redirects.map((entry) => [entry.source, entry]));

    // Section-level retirements that already existed.
    expect(byPath['/offline-activation']).toMatchObject({ destination: '/keys', permanent: true });
    expect(byPath['/top-ups']).toMatchObject({ destination: '/subscriptions', permanent: true });

    // Deleted top-up pages go to the same game's gift-card page when it exists...
    expect(byPath['/games/pubg-mobile/uc']).toMatchObject({
      destination: '/games/pubg-mobile/gift-cards',
      permanent: true,
    });
    expect(byPath['/games/free-fire/diamonds']).toMatchObject({
      destination: '/games/free-fire/gift-cards',
      permanent: true,
    });
    // The plain category-slug alias of a renamed page follows the same rule.
    expect(byPath['/games/pubg-mobile/top-ups']).toMatchObject({
      destination: '/games/pubg-mobile/gift-cards',
      permanent: true,
    });
    // ...and to the gift-cards section when the brand is gone entirely.
    expect(byPath['/games/netflix/gift-cards']).toMatchObject({ destination: '/gift-cards', permanent: true });
    expect(byPath['/games/netflix']).toMatchObject({ destination: '/gift-cards', permanent: true });

    // Offline activation: per-game exceptions first, then the wildcard to keys.
    const wildcardIndex = redirects.findIndex((entry) => entry.source === '/games/:game/offline-activation');
    expect(wildcardIndex).toBeGreaterThan(-1);
    expect(redirects[wildcardIndex]).toMatchObject({ destination: '/games/:game/keys', permanent: true });
    const exceptionIndex = redirects.findIndex((entry) => entry.source === '/games/alan-wake-2/offline-activation');
    expect(exceptionIndex).toBeGreaterThan(-1);
    expect(exceptionIndex).toBeLessThan(wildcardIndex);
    expect(redirects[exceptionIndex].destination).toBe('/games/alan-wake-2/rentals');
    expect(byPath['/games/epic-games/offline-activation'].destination).toBe('/keys');

    // Hygiene: every rule is permanent, site-relative, unique, and never
    // points at another retired URL (no redirect chains).
    const sources = redirects.map((entry) => entry.source);
    expect(new Set(sources).size).toBe(sources.length);
    for (const entry of redirects) {
      expect(entry.permanent).toBe(true);
      expect(entry.destination).toMatch(/^\//);
      expect(entry.destination).not.toBe(entry.source);
      expect(sources).not.toContain(entry.destination);
    }
  });
});

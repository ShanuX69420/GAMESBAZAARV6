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
});

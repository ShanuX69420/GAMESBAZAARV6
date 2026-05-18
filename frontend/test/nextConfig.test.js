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
  });

  it('leaves runtime security headers to proxy', async () => {
    vi.stubEnv('NODE_ENV', 'production');

    const { default: nextConfig } = await importFreshNextConfig();

    expect(nextConfig.headers).toBeUndefined();
  });
});

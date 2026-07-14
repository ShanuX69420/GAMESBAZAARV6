import { afterEach, describe, expect, it, vi } from 'vitest';

async function importFreshProxy() {
  const nextCalls = [];

  vi.resetModules();
  vi.doMock('next/server', () => ({
    NextResponse: {
      next: vi.fn((options) => {
        const response = { headers: new Headers(), options };
        nextCalls.push({ options, response });
        return response;
      }),
    },
  }));

  const module = await import('../proxy.js');
  return { module, nextCalls };
}

function runWithoutNodeBuffer(callback) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'Buffer');

  Object.defineProperty(globalThis, 'Buffer', {
    configurable: true,
    writable: true,
    value: undefined,
  });

  try {
    return callback();
  } finally {
    if (descriptor) {
      Object.defineProperty(globalThis, 'Buffer', descriptor);
    } else {
      delete globalThis.Buffer;
    }
  }
}

describe('security proxy', () => {
  afterEach(() => {
    vi.doUnmock('next/server');
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('skips custom security headers outside production', async () => {
    vi.stubEnv('NODE_ENV', 'development');
    const { module, nextCalls } = await importFreshProxy();

    const response = module.proxy({ headers: new Headers() });

    expect(nextCalls).toHaveLength(1);
    expect(nextCalls[0].options).toBeUndefined();
    expect([...response.headers.entries()]).toEqual([]);
  });

  it('sets a static allowlist CSP and hardening headers in production without Node Buffer', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.gamesbazaar.pk/v1');
    vi.stubEnv('NEXT_PUBLIC_WS_URL', 'wss://realtime.gamesbazaar.pk/socket');
    vi.stubEnv('NEXT_PUBLIC_IMAGE_HOSTS', 'cdn.gamesbazaar.pk, https://media.gamesbazaar.pk/images');
    const { module, nextCalls } = await importFreshProxy();

    const request = { headers: new Headers([['accept', 'text/html']]) };
    const response = runWithoutNodeBuffer(() => module.proxy(request));

    expect(nextCalls).toHaveLength(1);
    expect(nextCalls[0].options).toBeUndefined();
    expect(request.headers.get('x-nonce')).toBeNull();
    const csp = response.headers.get('Content-Security-Policy');

    expect(csp).not.toContain("'nonce-");
    expect(csp).not.toContain("'strict-dynamic'");
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain('https://api.gamesbazaar.pk');
    expect(csp).toContain('wss://realtime.gamesbazaar.pk');
    expect(csp).toContain('https://accounts.google.com/gsi/client');
    expect(csp).toContain('https://accounts.google.com/gsi/style');
    expect(csp).toContain('https://www.googletagmanager.com');
    expect(csp).toContain('https://www.google-analytics.com');
    expect(csp).toContain('https://pagead2.googlesyndication.com');
    expect(csp).toContain('https://googleads.g.doubleclick.net');
    expect(csp).toContain('https://connect.facebook.net');
    expect(csp).toContain('https://www.facebook.com');
    expect(csp).toContain('https://fonts.googleapis.com');
    expect(csp).toContain('https://fonts.gstatic.com');
    expect(csp).toContain('connect-src');
    expect(csp).toContain('https://accounts.google.com');
    expect(csp).toContain('frame-src https://accounts.google.com');
    expect(csp).toContain('https://cdn.gamesbazaar.pk');
    expect(csp).toContain('https://media.gamesbazaar.pk');
    expect(csp).toContain('upgrade-insecure-requests');

    expect(response.headers.get('Strict-Transport-Security')).toBe(
      'max-age=63072000; includeSubDomains'
    );
    expect(response.headers.get('X-Content-Type-Options')).toBe('nosniff');
    expect(response.headers.get('X-Frame-Options')).toBe('DENY');
    expect(response.headers.get('Referrer-Policy')).toBe('strict-origin-when-cross-origin');
    expect(response.headers.get('X-DNS-Prefetch-Control')).toBe('on');
    expect(response.headers.get('X-Permitted-Cross-Domain-Policies')).toBe('none');
    expect(response.headers.get('Permissions-Policy')).toContain('camera=()');
  });

  it('skips custom security headers for local production bundle testing', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('LOCAL_PRODUCTION_BUILD', '1');
    const { module, nextCalls } = await importFreshProxy();

    const response = module.proxy({ headers: new Headers() });

    expect(nextCalls).toHaveLength(1);
    expect(nextCalls[0].options).toBeUndefined();
    expect([...response.headers.entries()]).toEqual([]);
  });

  it('omits invalid API and websocket origins from CSP directives', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'not a url');
    vi.stubEnv('NEXT_PUBLIC_WS_URL', 'also not a url');
    vi.stubEnv('NEXT_PUBLIC_IMAGE_HOSTS', 'bad url, wss://not-an-image.example');
    const { module } = await importFreshProxy();

    const response = module.proxy({ headers: new Headers() });
    const csp = response.headers.get('Content-Security-Policy');

    expect(csp).toContain("img-src 'self' data: blob:");
    expect(csp).toContain("connect-src 'self'");
    expect(csp).not.toContain('not a url');
    expect(csp).not.toContain('also not a url');
    expect(csp).not.toContain('bad url');
    expect(csp).not.toContain('wss://not-an-image.example');
  });

  it('uses the same static CSP for prerendered and dynamic routes', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    const { module, nextCalls } = await importFreshProxy();

    const publicResponse = module.proxy({
      headers: new Headers(),
      nextUrl: { pathname: '/privacy-policy/' },
    });
    const notFoundResponse = module.proxy({
      headers: new Headers(),
      nextUrl: { pathname: '/_not-found' },
    });
    const publicCsp = publicResponse.headers.get('Content-Security-Policy');
    const notFoundCsp = notFoundResponse.headers.get('Content-Security-Policy');

    expect(nextCalls).toHaveLength(2);
    expect(nextCalls[0].options).toBeUndefined();
    expect(nextCalls[1].options).toBeUndefined();
    expect(publicCsp).toBe(notFoundCsp);
    expect(publicCsp).not.toContain("'nonce-");
    expect(publicCsp).not.toContain("'strict-dynamic'");
    expect(publicCsp).toContain("script-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/client");
  });

  it('includes HSTS preload when SECURE_HSTS_PRELOAD is set', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('SECURE_HSTS_PRELOAD', 'True');
    const { module } = await importFreshProxy();

    const response = module.proxy({ headers: new Headers() });

    expect(response.headers.get('Strict-Transport-Security')).toBe(
      'max-age=63072000; includeSubDomains; preload'
    );
  });

  it('matches browser pages while excluding API routes and static assets', async () => {
    const { module } = await importFreshProxy();

    expect(module.config.matcher).toEqual([
      {
        source: '/((?!api|_next/static|_next/image|favicon.ico|logo.png|apple-touch-icon.png|manifest.json|robots.txt|sitemap.xml|sitemap-listings).*)',
        missing: [
          { type: 'header', key: 'next-router-prefetch' },
          { type: 'header', key: 'purpose', value: 'prefetch' },
        ],
      },
    ]);
  });
});

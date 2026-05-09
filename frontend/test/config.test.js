import { afterEach, describe, expect, it, vi } from 'vitest';

async function importFreshConfig() {
  vi.resetModules();
  return import('../lib/config.js');
}

describe('frontend config', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('derives a websocket base from the API base when no explicit websocket URL is set', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.example.test/v1');
    vi.stubEnv('NEXT_PUBLIC_WS_URL', '');

    const config = await importFreshConfig();

    expect(config.API_BASE).toBe('https://api.example.test/v1');
    expect(config.WS_BASE).toBe('wss://api.example.test');
  });

  it('requires production API and websocket URLs to use secure protocols', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://api.example.test');
    vi.stubEnv('NEXT_PUBLIC_WS_URL', 'wss://api.example.test');

    await expect(importFreshConfig()).rejects.toThrow(
      'NEXT_PUBLIC_API_URL must use https: in production.'
    );
  });

  it('rejects localhost production endpoints', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://localhost:8000');
    vi.stubEnv('NEXT_PUBLIC_WS_URL', 'wss://api.example.test');

    await expect(importFreshConfig()).rejects.toThrow(
      'NEXT_PUBLIC_API_URL cannot point to localhost in production.'
    );
  });
});

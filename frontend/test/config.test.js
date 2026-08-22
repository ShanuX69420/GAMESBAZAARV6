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

  it('reads the API base from the environment', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.example.test/v1');

    const config = await importFreshConfig();

    expect(config.API_BASE).toBe('https://api.example.test/v1');
  });

  it('requires the production API URL to use a secure protocol', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://api.example.test');

    await expect(importFreshConfig()).rejects.toThrow(
      'NEXT_PUBLIC_API_URL must use https: in production.'
    );
  });

  it('rejects localhost production endpoints', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://localhost:8000');

    await expect(importFreshConfig()).rejects.toThrow(
      'NEXT_PUBLIC_API_URL cannot point to localhost in production.'
    );
  });

  it('allows localhost defaults for local production bundle testing', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('LOCAL_PRODUCTION_BUILD', '1');
    vi.stubEnv('NEXT_PUBLIC_API_URL', '');

    const config = await importFreshConfig();

    expect(config.API_BASE).toBe('http://localhost:8000');
  });

  it('allows explicit localhost endpoints for local production bundle testing', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('LOCAL_PRODUCTION_BUILD', 'true');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://localhost:8000');

    const config = await importFreshConfig();

    expect(config.API_BASE).toBe('http://localhost:8000');
  });

  it('does not throw config validation errors in the browser bundle', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://localhost:8000');
    vi.stubGlobal('window', {});

    const config = await importFreshConfig();

    expect(config.API_BASE).toBe('http://localhost:8000');
  });
});

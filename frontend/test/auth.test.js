import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE } from '../lib/config';
import { requestLogout } from '../lib/authRequests';

describe('auth helpers', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('posts logout with credentials', async () => {
    fetch.mockResolvedValueOnce({ ok: true });

    await requestLogout();

    expect(fetch).toHaveBeenCalledWith(`${API_BASE}/api/auth/logout/`, {
      method: 'POST',
      credentials: 'include',
    });
  });

  it('does not throw when the API is unreachable during logout', async () => {
    fetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));

    await expect(requestLogout()).resolves.toBeUndefined();
  });

  it('warns in development when logout response is not ok', async () => {
    vi.stubEnv('NODE_ENV', 'development');
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    fetch.mockResolvedValueOnce({ ok: false, status: 403 });

    await requestLogout();

    expect(warnSpy).toHaveBeenCalledWith('Logout request failed with status 403');
  });

  it('does not warn in production when logout response is not ok', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    fetch.mockResolvedValueOnce({ ok: false, status: 500 });

    await requestLogout();

    expect(warnSpy).not.toHaveBeenCalled();
  });
});

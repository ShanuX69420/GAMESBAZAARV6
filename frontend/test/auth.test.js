import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE } from '../lib/config';
import { formatApiError, requestLogout } from '../lib/authRequests';

describe('formatApiError', () => {
  it('joins every field error so all the rules show at once', () => {
    const message = formatApiError({
      password: [
        'The password is too similar to the username.',
        'This password is too common.',
      ],
    }, 'Registration failed');

    expect(message).toBe(
      'The password is too similar to the username. This password is too common.'
    );
  });

  it('rewrites the throttle message in minutes', () => {
    const message = formatApiError(
      { detail: 'Request was throttled. Expected available in 3226 seconds.' },
      'Registration failed'
    );

    expect(message).toBe(
      'Too many attempts from your network. Please try again in about 54 minutes.'
    );
  });

  it('rounds a long throttle window to hours', () => {
    const message = formatApiError(
      { detail: 'Request was throttled. Expected available in 7200 seconds.' },
      'Registration failed'
    );

    expect(message).toContain('about 2 hours');
  });

  it('falls back when the body carries no readable message', () => {
    expect(formatApiError({}, 'Registration failed')).toBe('Registration failed');
    expect(formatApiError(null, 'Registration failed')).toBe('Registration failed');
  });
});

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

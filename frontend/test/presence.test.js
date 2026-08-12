import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE } from '../lib/config';
import { getPresence } from '../lib/api';
import { pickLastActive } from '../lib/presence';

function jsonResponse(data = {}, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => null },
    json: vi.fn().mockResolvedValue(data),
  };
}

describe('pickLastActive', () => {
  const older = '2026-08-12T10:00:00Z';
  const newer = '2026-08-12T10:01:00Z';

  it('falls back to the payload timestamp until live presence arrives', () => {
    expect(pickLastActive(undefined, older)).toBe(older);
    expect(pickLastActive(null, null)).toBe(null);
  });

  it('takes the live timestamp over a cached payload one', () => {
    expect(pickLastActive(newer, older)).toBe(newer);
  });

  it('never regresses to an older answer', () => {
    // A poll answered from before the payload was rendered must not drag a
    // seller who just heartbeated back to "offline".
    expect(pickLastActive(older, newer)).toBe(newer);
  });
});

describe('getPresence', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ users: {} })));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('asks for each seller once and forbids caching the answer', async () => {
    await getPresence([7, 7, 9]);

    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE}/api/presence/?user_ids=7%2C9`,
      { cache: 'no-store' },
    );
  });

  it('skips the request entirely when there is nobody to look up', async () => {
    const result = await getPresence([null, undefined]);

    expect(result).toEqual({});
    expect(fetch).not.toHaveBeenCalled();
  });

  it('returns the user map', async () => {
    const lastActive = '2026-08-12T10:00:00Z';
    fetch.mockResolvedValueOnce(jsonResponse({ users: { 7: lastActive } }));

    await expect(getPresence([7])).resolves.toEqual({ 7: lastActive });
  });
});

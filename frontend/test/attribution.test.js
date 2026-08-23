import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE } from '../lib/config';
import { attributionBody, captureFirstTouch, getFirstTouch } from '../lib/attribution';
import { initiateGuestJazzCashPurchase } from '../lib/api';

function fakeStorage(initial = {}) {
  const store = { ...initial };
  return {
    getItem: (key) => (key in store ? store[key] : null),
    setItem: (key, value) => { store[key] = String(value); },
    _store: store,
  };
}

function stubBrowser({ referrer = '', pathname = '/', search = '', storage } = {}) {
  const localStorage = storage || fakeStorage();
  vi.stubGlobal('window', {});
  vi.stubGlobal('document', { referrer });
  vi.stubGlobal('location', { pathname, search });
  vi.stubGlobal('localStorage', localStorage);
  return localStorage;
}

describe('first-touch attribution stash', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('captures referrer, landing path+query and a timestamp on first load', () => {
    stubBrowser({
      referrer: 'https://www.google.com/',
      pathname: '/listing/28402',
      search: '?utm_source=chatgpt.com',
    });
    captureFirstTouch();

    const stash = getFirstTouch();
    expect(stash.referrer).toBe('https://www.google.com/');
    expect(stash.landing_page).toBe('/listing/28402?utm_source=chatgpt.com');
    expect(new Date(stash.first_seen_at).getTime()).not.toBeNaN();
  });

  it('never overwrites an existing stash', () => {
    const storage = stubBrowser({ referrer: 'https://www.google.com/' });
    captureFirstTouch();
    const first = storage._store.gb_first_touch;

    vi.stubGlobal('document', { referrer: 'https://www.facebook.com/' });
    vi.stubGlobal('location', { pathname: '/wallet', search: '' });
    captureFirstTouch();

    expect(storage._store.gb_first_touch).toBe(first);
  });

  it('returns an empty body when nothing was captured or storage is unavailable', () => {
    stubBrowser();
    expect(attributionBody()).toEqual({});

    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('denied'); },
    });
    expect(attributionBody()).toEqual({});

    vi.unstubAllGlobals();
    // No window at all (SSR) — still silently empty.
    expect(attributionBody()).toEqual({});
  });

  it('rides along in the guest checkout body', async () => {
    stubBrowser({
      storage: fakeStorage({
        gb_first_touch: JSON.stringify({
          referrer: '',
          landing_page: '/listing/5',
          first_seen_at: '2026-08-23T13:50:00.000Z',
        }),
      }),
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: vi.fn().mockResolvedValue({}),
    }));

    await initiateGuestJazzCashPurchase(7, 1, '03001234567', 'guest@example.com');

    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.attribution).toEqual({
      referrer: '',
      landing_page: '/listing/5',
      first_seen_at: '2026-08-23T13:50:00.000Z',
    });
  });
});

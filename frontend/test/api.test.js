import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE } from '../lib/config';
import {
  getConversations,
  getMyListings,
  getSellerDashboard,
  getSellerProfile,
  getSellerReviews,
  searchMarketplace,
} from '../lib/api';

function jsonResponse(data = {}, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(data),
  };
}

describe('API client helpers', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ok: true })));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('encodes listing filter query params for my listings', async () => {
    await getMyListings({
      limit: 10,
      offset: 20,
      status: 'active',
      search: 'gold rank',
      game: 'pubg mobile',
      category: 'accounts',
      includeFacets: false,
    });

    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE}/api/listings/mine/?limit=10&offset=20&status=active&search=gold+rank&game=pubg+mobile&category=accounts&include_facets=0`,
      {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      }
    );
  });

  it('encodes shared pagination aliases for conversations', async () => {
    await getConversations({ limit: 5, beforeId: 42, otherUserId: 'seller+pk@example.com' });

    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE}/api/chat/?limit=5&before_id=42&other_user_id=seller%2Bpk%40example.com`,
      {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      }
    );
  });

  it('encodes seller review/profile path segments and review pagination', async () => {
    await getSellerReviews('seller+pk@example.com', { limit: 20, offset: 40 });
    await getSellerProfile('seller+pk@example.com');

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      `${API_BASE}/api/reviews/seller/seller%2Bpk%40example.com/?limit=20&offset=40`
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      `${API_BASE}/api/seller/profile/seller%2Bpk%40example.com/`
    );
  });

  it('encodes marketplace search queries', async () => {
    await searchMarketplace('valorant prime+boost');

    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE}/api/search/?q=valorant+prime%2Bboost`
    );
  });

  it('refreshes auth cookies once before retrying a 401 response', async () => {
    fetch
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({}, 200))
      .mockResolvedValueOnce(jsonResponse({ total_sales: 3 }, 200));

    const data = await getSellerDashboard();

    expect(data).toEqual({ total_sales: 3 });
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      `${API_BASE}/api/seller/dashboard/`,
      {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      }
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      `${API_BASE}/api/auth/refresh/`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({}),
      }
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      `${API_BASE}/api/seller/dashboard/`,
      {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      }
    );
  });
});

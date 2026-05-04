import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE } from '../lib/config';
import {
  getConversations,
  getMyListings,
  getMyOrders,
  getMyReports,
  getWithdrawRequests,
  requestWithdraw,
  getSellerDashboard,
  getSellerProfile,
  getSellerReviews,
  searchMarketplace,
  submitReport,
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

  it('encodes cursor pagination for orders', async () => {
    await getMyOrders({ limit: 20, beforeId: 42, cursor: true });

    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE}/api/orders/mine/?limit=20&before_id=42&cursor=1`,
      {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      }
    );
  });

  it('serializes withdrawal requests and paginates withdrawal history', async () => {
    await requestWithdraw(
      '500.00',
      'Bank Transfer',
      'Buyer Account',
      'PK36MEZN0001234567890123',
      'Meezan Bank'
    );
    await getWithdrawRequests({ limit: 20, offset: 40 });

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      `${API_BASE}/api/wallet/withdraw/`,
      {
        credentials: 'include',
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount: '500.00',
          payment_method: 'Bank Transfer',
          account_title: 'Buyer Account',
          account_details: 'PK36MEZN0001234567890123',
          bank_name: 'Meezan Bank',
        }),
      }
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      `${API_BASE}/api/wallet/withdraw/?limit=20&offset=40`,
      {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      }
    );
  });

  it('serializes report submissions and report pagination', async () => {
    await submitReport({
      targetType: 'listing',
      listingId: 7,
      reason: 'scam',
      description: 'Suspicious listing.',
    });
    await getMyReports({ limit: 10, offset: 20 });

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      `${API_BASE}/api/reports/`,
      {
        credentials: 'include',
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_type: 'listing',
          reason: 'scam',
          description: 'Suspicious listing.',
          listing_id: 7,
        }),
      }
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      `${API_BASE}/api/reports/mine/?limit=10&offset=20`,
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

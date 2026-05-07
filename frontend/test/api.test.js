import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE } from '../lib/config';
import {
  confirmOrder,
  deliverOrder,
  disputeOrder,
  getConversations,
  getMySupportTickets,
  getMyListings,
  getMyOrders,
  getMyReports,
  getOrderDetail,
  getWithdrawRequests,
  refundOrder,
  replyToReview,
  requestWithdraw,
  getSellerDashboard,
  getSellerProfile,
  getSellerReviews,
  searchMarketplace,
  submitReport,
  submitSupportTicket,
  updateReview,
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

  it('encodes public order references for order detail and actions', async () => {
    const orderRef = 'GB-ABCD+EFGH/IJKL';

    await getOrderDetail(orderRef);
    await deliverOrder(orderRef, 'Delivered');
    await confirmOrder(orderRef);
    await disputeOrder(orderRef, 'Missing item');
    await refundOrder(orderRef);

    const encoded = 'GB-ABCD%2BEFGH%2FIJKL';
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      `${API_BASE}/api/orders/${encoded}/`,
      {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      }
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      `${API_BASE}/api/orders/${encoded}/deliver/`,
      {
        credentials: 'include',
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ delivery_note: 'Delivered' }),
      }
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      `${API_BASE}/api/orders/${encoded}/confirm/`,
      {
        credentials: 'include',
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      }
    );
    expect(fetch).toHaveBeenNthCalledWith(
      4,
      `${API_BASE}/api/orders/${encoded}/dispute/`,
      {
        credentials: 'include',
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Missing item' }),
      }
    );
    expect(fetch).toHaveBeenNthCalledWith(
      5,
      `${API_BASE}/api/orders/${encoded}/refund/`,
      {
        credentials: 'include',
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      }
    );
  });

  it('serializes review update and seller reply helpers', async () => {
    await updateReview(12, 4, 'Updated review');
    await replyToReview(12, 'Thanks for the review');

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      `${API_BASE}/api/reviews/12/`,
      {
        credentials: 'include',
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating: 4, comment: 'Updated review' }),
      }
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      `${API_BASE}/api/reviews/12/reply/`,
      {
        credentials: 'include',
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reply: 'Thanks for the review' }),
      }
    );
  });

  it('serializes support ticket creation and support history pagination', async () => {
    await submitSupportTicket({
      name: 'Guest Buyer',
      email: 'guest@example.com',
      category: 'order',
      subject: 'Order help',
      message: 'I need help with an order.',
      orderId: 1234,
    });
    await getMySupportTickets({ limit: 10, offset: 20 });

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      `${API_BASE}/api/support/`,
      {
        credentials: 'include',
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category: 'order',
          subject: 'Order help',
          message: 'I need help with an order.',
          name: 'Guest Buyer',
          email: 'guest@example.com',
          order_id: 1234,
        }),
      }
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      `${API_BASE}/api/support/mine/?limit=10&offset=20`,
      {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      }
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

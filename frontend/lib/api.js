import { API_BASE } from '@/lib/config';
let refreshAuthPromise = null;

function paginationQuery({ limit, offset, beforeId, before_id, otherUserId, other_user_id } = {}) {
  const params = new URLSearchParams();
  if (limit !== undefined && limit !== null) params.set('limit', String(limit));
  if (offset !== undefined && offset !== null) params.set('offset', String(offset));
  const cursor = beforeId ?? before_id;
  if (cursor !== undefined && cursor !== null) params.set('before_id', String(cursor));
  const participant = otherUserId ?? other_user_id;
  if (participant !== undefined && participant !== null) params.set('other_user_id', String(participant));
  const query = params.toString();
  return query ? `?${query}` : '';
}

// ── Public API (server-side) ────────────────────────────────────────────────

export async function fetchGames() {
  const res = await fetch(`${API_BASE}/api/games/`, { cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to fetch games');
  return res.json();
}

export async function fetchGame(slug) {
  const res = await fetch(`${API_BASE}/api/games/${slug}/`, { cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to fetch game');
  return res.json();
}

export async function fetchGameCategory(gameSlug, categorySlug, filterParams = '') {
  const url = `${API_BASE}/api/games/${gameSlug}/${categorySlug}/${filterParams ? '?' + filterParams : ''}`;
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to fetch game category');
  return res.json();
}

// ── Authenticated API (client-side) ─────────────────────────────────────────

function authHeaders() {
  return {
    'Content-Type': 'application/json',
  };
}

async function refreshAuthCookies() {
  if (!refreshAuthPromise) {
    refreshAuthPromise = fetch(`${API_BASE}/api/auth/refresh/`, {
      method: 'POST',
      headers: authHeaders(),
      credentials: 'include',
      body: JSON.stringify({}),
    })
      .then((res) => res.ok)
      .catch(() => false)
      .finally(() => {
        refreshAuthPromise = null;
      });
  }

  return refreshAuthPromise;
}

async function authFetch(url, options = {}, retry = true) {
  const res = await fetch(url, {
    credentials: 'include',
    ...options,
  });
  if (res.status !== 401 || !retry) {
    return res;
  }

  const refreshed = await refreshAuthCookies();
  if (!refreshed) {
    return res;
  }

  return authFetch(url, options, false);
}

export async function applyAsSeller(note) {
  const res = await authFetch(`${API_BASE}/api/seller/apply/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ note }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Application failed');
  return data;
}

export async function getSellerStatus() {
  const res = await authFetch(`${API_BASE}/api/seller/status/`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get seller status');
  return res.json();
}

export async function getSellerDashboard() {
  const res = await authFetch(`${API_BASE}/api/seller/dashboard/`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get seller dashboard');
  return res.json();
}

export async function createListing(listingData) {
  const res = await authFetch(`${API_BASE}/api/listings/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(listingData),
  });
  const data = await res.json();
  if (!res.ok) {
    const errors = Object.values(data).flat();
    throw new Error(errors[0] || 'Failed to create listing');
  }
  return data;
}

export async function getMyListings({ limit, offset, status, search, game, category, includeFacets } = {}) {
  const params = new URLSearchParams();
  if (limit !== undefined && limit !== null) params.set('limit', String(limit));
  if (offset !== undefined && offset !== null) params.set('offset', String(offset));
  if (status) params.set('status', status);
  if (search) params.set('search', search);
  if (game) params.set('game', game);
  if (category) params.set('category', category);
  if (includeFacets === false) params.set('include_facets', '0');
  const query = params.toString();
  const res = await authFetch(`${API_BASE}/api/listings/mine/${query ? '?' + query : ''}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get listings');
  return res.json();
}

export async function getListingDetail(id) {
  const res = await fetch(`${API_BASE}/api/listings/${id}/`, {
    cache: 'no-store',
  });
  if (!res.ok) throw new Error('Failed to get listing');
  return res.json();
}

export async function updateListing(id, data) {
  const res = await authFetch(`${API_BASE}/api/listings/${id}/`, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify(data),
  });
  const result = await res.json();
  if (!res.ok) {
    const errors = Object.values(result).flat();
    throw new Error(errors[0] || 'Failed to update listing');
  }
  return result;
}

export async function deleteListing(id) {
  const res = await authFetch(`${API_BASE}/api/listings/${id}/`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok && res.status !== 204) {
    throw new Error('Failed to delete listing');
  }
  return true;
}

// ── Chat API ────────────────────────────────────────────────────────────────

export async function getConversations(pagination = {}) {
  const res = await authFetch(`${API_BASE}/api/chat/${paginationQuery(pagination)}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get conversations');
  return res.json();
}

export async function startConversation(userId, message = '') {
  const res = await authFetch(`${API_BASE}/api/chat/start/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ user_id: userId, message }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to start conversation');
  return data;
}

export async function getConversation(id, pagination = {}) {
  const res = await authFetch(`${API_BASE}/api/chat/${id}/${paginationQuery(pagination)}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get conversation');
  return res.json();
}

export async function getChatWebSocketTicket(conversationId) {
  const res = await authFetch(`${API_BASE}/api/chat/${conversationId}/ws-ticket/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({}),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to get chat connection ticket');
  return data;
}

export async function sendMessage(conversationId, content) {
  const res = await authFetch(`${API_BASE}/api/chat/${conversationId}/send/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ content }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to send message');
  return data;
}

export async function getUnreadCount() {
  const res = await authFetch(`${API_BASE}/api/chat/unread/`, {
    headers: authHeaders(),
  });
  if (!res.ok) return { unread_count: 0 };
  return res.json();
}

export async function sendImageMessage(conversationId, imageFile, content = '') {
  const formData = new FormData();
  formData.append('image', imageFile);
  if (content) formData.append('content', content);

  const res = await authFetch(`${API_BASE}/api/chat/${conversationId}/send-image/`, {
    method: 'POST',
    body: formData,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to send image');
  return data;
}

// ── Presence API ────────────────────────────────────────────────────────────

export async function sendHeartbeat() {
  const res = await authFetch(`${API_BASE}/api/heartbeat/`, {
    method: 'POST',
    headers: authHeaders(),
  });
  return res.ok;
}

export function formatLastActive(isoString) {
  if (!isoString) return 'Offline';
  const date = new Date(isoString);
  const now = new Date();
  const diff = (now - date) / 1000; // seconds

  if (diff < 120) return 'Online';
  if (diff < 3600) return `Active ${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `Active ${Math.floor(diff / 3600)}h ago`;
  return `Active ${Math.floor(diff / 86400)}d ago`;
}

// ── Wallet API ──────────────────────────────────────────────────────────────

export async function getWallet(pagination = {}) {
  const res = await authFetch(`${API_BASE}/api/wallet/${paginationQuery(pagination)}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get wallet');
  return res.json();
}

export async function getWalletTransactions(pagination = {}) {
  const res = await authFetch(`${API_BASE}/api/wallet/transactions/${paginationQuery(pagination)}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get transactions');
  return res.json();
}

export async function requestTopUp(amount, paymentMethod = '', transactionId = '', paymentProof = null) {
  const formData = new FormData();
  formData.append('amount', amount);
  if (paymentMethod) formData.append('payment_method', paymentMethod);
  if (transactionId) formData.append('transaction_id', transactionId);
  if (paymentProof) formData.append('payment_proof', paymentProof);

  const res = await authFetch(`${API_BASE}/api/wallet/top-up/`, {
    method: 'POST',
    body: formData,
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(
      data.error ||
      data.amount?.[0] ||
      data.transaction_id?.[0] ||
      data.payment_proof?.[0] ||
      'Top-up request failed'
    );
  }
  return data;
}

export async function getTopUpRequests(pagination = {}) {
  const res = await authFetch(`${API_BASE}/api/wallet/top-up/${paginationQuery(pagination)}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get top-up requests');
  return res.json();
}

// ── Orders API ──────────────────────────────────────────────────────────────

export async function buyListing(listingId, quantity = 1) {
  const res = await authFetch(`${API_BASE}/api/orders/buy/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ listing_id: listingId, quantity }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Purchase failed');
  return data;
}

export async function getMyOrders({ limit, offset, status, search, date_from, date_to } = {}) {
  const params = new URLSearchParams();
  if (limit !== undefined && limit !== null) params.set('limit', String(limit));
  if (offset !== undefined && offset !== null) params.set('offset', String(offset));
  if (status) params.set('status', status);
  if (search) params.set('search', search);
  if (date_from) params.set('date_from', date_from);
  if (date_to) params.set('date_to', date_to);
  const query = params.toString();
  const res = await authFetch(`${API_BASE}/api/orders/mine/${query ? '?' + query : ''}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get orders');
  return res.json();
}

export async function getMySales({ limit, offset, status, search, date_from, date_to } = {}) {
  const params = new URLSearchParams();
  if (limit !== undefined && limit !== null) params.set('limit', String(limit));
  if (offset !== undefined && offset !== null) params.set('offset', String(offset));
  if (status) params.set('status', status);
  if (search) params.set('search', search);
  if (date_from) params.set('date_from', date_from);
  if (date_to) params.set('date_to', date_to);
  const query = params.toString();
  const res = await authFetch(`${API_BASE}/api/orders/sales/${query ? '?' + query : ''}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get sales');
  return res.json();
}

export async function getOrderDetail(id) {
  const res = await authFetch(`${API_BASE}/api/orders/${id}/`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get order');
  return res.json();
}

export async function deliverOrder(id, deliveryNote = '') {
  const res = await authFetch(`${API_BASE}/api/orders/${id}/deliver/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ delivery_note: deliveryNote }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to deliver order');
  return data;
}

export async function confirmOrder(id) {
  const res = await authFetch(`${API_BASE}/api/orders/${id}/confirm/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({}),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to confirm order');
  return data;
}

export async function disputeOrder(id, reason) {
  const res = await authFetch(`${API_BASE}/api/orders/${id}/dispute/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ reason }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to dispute order');
  return data;
}

export async function refundOrder(id) {
  const res = await authFetch(`${API_BASE}/api/orders/${id}/refund/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({}),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to refund order');
  return data;
}

// ── Reviews API ─────────────────────────────────────────────────────────────

export async function createReview(orderId, rating, comment = '') {
  const res = await authFetch(`${API_BASE}/api/reviews/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ order_id: orderId, rating, comment }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to submit review');
  return data;
}

export async function getSellerReviews(username, pagination = {}) {
  const res = await fetch(`${API_BASE}/api/reviews/seller/${username}/${paginationQuery(pagination)}`);
  if (!res.ok) throw new Error('Failed to get reviews');
  return res.json();
}

export async function getSellerProfile(username) {
  const res = await fetch(`${API_BASE}/api/seller/profile/${username}/`);
  if (!res.ok) throw new Error('Failed to get seller profile');
  return res.json();
}

// ── Search API ──────────────────────────────────────────────────────────────

export async function searchMarketplace(query) {
  const params = new URLSearchParams({ q: query });
  const res = await fetch(`${API_BASE}/api/search/?${params.toString()}`);
  if (!res.ok) throw new Error('Search failed');
  return res.json();
}

// -- Notifications API --

export async function getNotifications(opts = {}) {
  const qs = paginationQuery(opts);
  const res = await authFetch(`${API_BASE}/api/notifications/${qs}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get notifications');
  return res.json();
}

export async function markNotificationRead(notificationId = 'all') {
  const res = await authFetch(`${API_BASE}/api/notifications/read/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ notification_id: notificationId }),
  });
  if (!res.ok) throw new Error('Failed to mark notification read');
  return res.json();
}

export async function getNotificationUnreadCount() {
  const res = await authFetch(`${API_BASE}/api/notifications/unread-count/`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get notification count');
  return res.json();
}

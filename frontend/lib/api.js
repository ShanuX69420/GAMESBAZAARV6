import { API_BASE } from '@/lib/config';
let refreshAuthPromise = null;
const GAME_LIST_REVALIDATE_SECONDS = 60;
const PUBLIC_CATALOG_REVALIDATE_SECONDS = 120;

let serverTimeOffset = 0;

function updateServerTimeOffset(res) {
  try {
    const serverDateStr = res.headers.get('Date');
    if (serverDateStr) {
      const serverTime = new Date(serverDateStr).getTime();
      if (!Number.isNaN(serverTime)) {
        serverTimeOffset = serverTime - Date.now();
      }
    }
  } catch (e) {
    // Ignore
  }
}

function pathSegment(value) {
  return encodeURIComponent(String(value));
}

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
  const res = await fetch(`${API_BASE}/api/games/`, {
    next: { revalidate: GAME_LIST_REVALIDATE_SECONDS },
  });
  updateServerTimeOffset(res);
  if (!res.ok) throw new Error('Failed to fetch games');
  return res.json();
}

export async function fetchGame(slug) {
  const res = await fetch(`${API_BASE}/api/games/${pathSegment(slug)}/`, {
    next: { revalidate: PUBLIC_CATALOG_REVALIDATE_SECONDS },
  });
  updateServerTimeOffset(res);
  if (!res.ok) throw new Error('Failed to fetch game');
  return res.json();
}

export async function fetchGameCategory(gameSlug, categorySlug, filterParams = '') {
  const url = `${API_BASE}/api/games/${pathSegment(gameSlug)}/${pathSegment(categorySlug)}/${filterParams ? '?' + filterParams : ''}`;
  const res = await fetch(url, {
    next: { revalidate: PUBLIC_CATALOG_REVALIDATE_SECONDS },
  });
  updateServerTimeOffset(res);
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
  updateServerTimeOffset(res);
  if (res.status !== 401 || !retry) {
    return res;
  }

  const refreshed = await refreshAuthCookies();
  if (!refreshed) {
    return res;
  }

  const retryRes = await authFetch(url, options, false);
  updateServerTimeOffset(retryRes);
  return retryRes;
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

export async function restockAutoDeliveryListing(id, data) {
  const res = await authFetch(`${API_BASE}/api/listings/${id}/restock/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(data),
  });
  const result = await res.json();
  if (!res.ok) {
    const errors = Object.values(result).flat();
    throw new Error(errors[0] || result.error || 'Failed to restock listing');
  }
  return result;
}

export async function getAutoDeliveryStock(id) {
  const res = await authFetch(`${API_BASE}/api/listings/${id}/stock/`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const result = await res.json();
    throw new Error(result.error || 'Failed to get stock');
  }
  return res.json();
}

export async function getAutoDeliveryStockItem(id, index) {
  const res = await authFetch(`${API_BASE}/api/listings/${id}/stock/?view=${index}`, {
    headers: authHeaders(),
  });
  const result = await res.json();
  if (!res.ok) {
    throw new Error(result.error || 'Failed to get stock item');
  }
  return result;
}

export async function updateAutoDeliveryStock(id, updates) {
  const res = await authFetch(`${API_BASE}/api/listings/${id}/stock/`, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify({ updates }),
  });
  const result = await res.json();
  if (!res.ok) {
    throw new Error(result.error || 'Failed to update stock');
  }
  return result;
}

export async function removeAutoDeliveryStock(id, indices) {
  const res = await authFetch(`${API_BASE}/api/listings/${id}/stock/`, {
    method: 'DELETE',
    headers: authHeaders(),
    body: JSON.stringify({ indices }),
  });
  const result = await res.json();
  if (!res.ok) {
    throw new Error(result.error || 'Failed to remove stock items');
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
  const { signal, ...paginationParams } = pagination;
  const res = await authFetch(`${API_BASE}/api/chat/${id}/${paginationQuery(paginationParams)}`, {
    headers: authHeaders(),
    ...(signal ? { signal } : {}),
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

const ONLINE_WINDOW_MS = 120000;

export function isOnlineFromLastActive(isoString, nowMs = Date.now()) {
  if (!isoString) return false;
  const lastActiveMs = new Date(isoString).getTime();
  if (Number.isNaN(lastActiveMs)) return false;
  const adjustedNow = nowMs + serverTimeOffset;
  return adjustedNow - lastActiveMs < ONLINE_WINDOW_MS;
}

export function formatLastActive(isoString) {
  if (!isoString) return 'Offline';
  const date = new Date(isoString);
  const adjustedNow = Date.now() + serverTimeOffset;
  const diff = (adjustedNow - date.getTime()) / 1000; // seconds

  if (isOnlineFromLastActive(isoString, Date.now())) return 'Online';
  if (diff < 3600) return `Active ${Math.floor(Math.max(0, diff) / 60)}m ago`;
  if (diff < 86400) return `Active ${Math.floor(Math.max(0, diff) / 3600)}h ago`;
  return `Active ${Math.floor(Math.max(0, diff) / 86400)}d ago`;
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

export async function requestWithdraw(amount, paymentMethod, accountTitle, accountDetails, bankName) {
  const res = await authFetch(`${API_BASE}/api/wallet/withdraw/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      amount,
      payment_method: paymentMethod,
      account_title: accountTitle,
      account_details: accountDetails,
      bank_name: bankName || '',
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(
      data.error ||
      data.amount?.[0] ||
      data.payment_method?.[0] ||
      data.account_title?.[0] ||
      data.account_details?.[0] ||
      'Withdrawal request failed'
    );
  }
  return data;
}

export async function getWithdrawRequests(pagination = {}) {
  const res = await authFetch(`${API_BASE}/api/wallet/withdraw/${paginationQuery(pagination)}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get withdrawal requests');
  return res.json();
}

export async function getHeldOrders(pagination = {}) {
  const res = await authFetch(`${API_BASE}/api/wallet/held-orders/${paginationQuery(pagination)}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get held orders');
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

export async function getMyOrders({ limit, offset, beforeId, status, search, date_from, date_to, cursor } = {}) {
  const params = new URLSearchParams();
  if (limit !== undefined && limit !== null) params.set('limit', String(limit));
  if (offset !== undefined && offset !== null) params.set('offset', String(offset));
  if (beforeId !== undefined && beforeId !== null) params.set('before_id', String(beforeId));
  if (cursor) params.set('cursor', '1');
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

export async function getMySales({ limit, offset, beforeId, status, search, date_from, date_to, cursor } = {}) {
  const params = new URLSearchParams();
  if (limit !== undefined && limit !== null) params.set('limit', String(limit));
  if (offset !== undefined && offset !== null) params.set('offset', String(offset));
  if (beforeId !== undefined && beforeId !== null) params.set('before_id', String(beforeId));
  if (cursor) params.set('cursor', '1');
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
  const res = await authFetch(`${API_BASE}/api/orders/${pathSegment(id)}/`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get order');
  return res.json();
}

export async function deliverOrder(id, deliveryNote = '') {
  const res = await authFetch(`${API_BASE}/api/orders/${pathSegment(id)}/deliver/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ delivery_note: deliveryNote }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to deliver order');
  return data;
}

export async function confirmOrder(id) {
  const res = await authFetch(`${API_BASE}/api/orders/${pathSegment(id)}/confirm/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({}),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to confirm order');
  return data;
}

export async function disputeOrder(id, reason) {
  const res = await authFetch(`${API_BASE}/api/orders/${pathSegment(id)}/dispute/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ reason }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to dispute order');
  return data;
}

export async function refundOrder(id) {
  const res = await authFetch(`${API_BASE}/api/orders/${pathSegment(id)}/refund/`, {
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
  const res = await fetch(`${API_BASE}/api/reviews/seller/${pathSegment(username)}/${paginationQuery(pagination)}`);
  if (!res.ok) throw new Error('Failed to get reviews');
  return res.json();
}

export async function updateReview(reviewId, rating, comment = '') {
  const res = await authFetch(`${API_BASE}/api/reviews/${reviewId}/`, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify({ rating, comment }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to update review');
  return data;
}

export async function replyToReview(reviewId, reply) {
  const res = await authFetch(`${API_BASE}/api/reviews/${reviewId}/reply/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ reply }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to reply to review');
  return data;
}

export async function getSellerProfile(username, options = {}) {
  const url = `${API_BASE}/api/seller/profile/${pathSegment(username)}/`;
  const requestOptions = options.signal ? { signal: options.signal } : undefined;
  const res = requestOptions ? await fetch(url, requestOptions) : await fetch(url);
  updateServerTimeOffset(res);
  if (!res.ok) throw new Error('Failed to get seller profile');
  return res.json();
}

// ── Search API ──────────────────────────────────────────────────────────────

export async function searchMarketplace(query) {
  const params = new URLSearchParams({ q: query });
  const res = await fetch(`${API_BASE}/api/search/?${params.toString()}`);
  updateServerTimeOffset(res);
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

// ── Settings API ────────────────────────────────────────────────────────────

export async function updateProfile(data) {
  const res = await authFetch(`${API_BASE}/api/auth/profile/`, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify(data),
  });
  const result = await res.json();
  if (!res.ok) {
    const errors = Object.values(result).flat();
    throw new Error(errors[0] || 'Failed to update profile');
  }
  return result;
}

export async function requestEmailChange(newEmail) {
  const res = await authFetch(`${API_BASE}/api/auth/email/request-change/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ new_email: newEmail }),
  });
  const data = await res.json();
  if (!res.ok) {
    const errors = Object.values(data).flat();
    throw new Error(errors[0] || 'Failed to request email change');
  }
  return data;
}

export async function confirmEmailChange(token, currentCode, newCode) {
  const res = await authFetch(`${API_BASE}/api/auth/email/confirm-change/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ token, current_code: currentCode, new_code: newCode }),
  });
  const data = await res.json();
  if (!res.ok) {
    const errors = Object.values(data).flat();
    throw new Error(errors[0] || 'Failed to confirm email change');
  }
  return data;
}

export async function changePassword(currentPassword, newPassword, newPassword2) {
  const res = await authFetch(`${API_BASE}/api/auth/password/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
      new_password2: newPassword2,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    const errors = Object.values(data).flat();
    throw new Error(errors[0] || 'Failed to change password');
  }
  return data;
}

export async function uploadAvatar(imageFile) {
  const formData = new FormData();
  formData.append('avatar', imageFile);

  const res = await authFetch(`${API_BASE}/api/auth/avatar/`, {
    method: 'POST',
    body: formData,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to upload avatar');
  return data;
}

export async function removeAvatar() {
  const res = await authFetch(`${API_BASE}/api/auth/avatar/`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to remove avatar');
  return data;
}

export async function requestPasswordReset(email) {
  const res = await fetch(`${API_BASE}/api/auth/password/reset-request/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to request password reset');
  return data;
}

export async function confirmPasswordReset(token, code, newPassword, newPassword2) {
  const res = await fetch(`${API_BASE}/api/auth/password/reset-confirm/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, code, new_password: newPassword, new_password2: newPassword2 }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to reset password');
  return data;
}

// ── Reports / Flags API ─────────────────────────────────────────────────────

export async function submitReport({ targetType, listingId, userId, reason, description }) {
  const body = { target_type: targetType, reason, description: description || '' };
  if (targetType === 'listing') body.listing_id = listingId;
  if (targetType === 'user') body.user_id = userId;

  const res = await authFetch(`${API_BASE}/api/reports/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || Object.values(data).flat()[0] || 'Failed to submit report');
  return data;
}

export async function getMyReports(pagination = {}) {
  const qs = paginationQuery(pagination);
  const res = await authFetch(`${API_BASE}/api/reports/mine/${qs}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get reports');
  return res.json();
}

// ── Support Tickets API ─────────────────────────────────────────────────────

export async function submitSupportTicket({ name, email, category, subject, message, orderId }) {
  const body = { category, subject, message };
  if (name) body.name = name;
  if (email) body.email = email;
  if (orderId) body.order_id = orderId;

  const res = await authFetch(`${API_BASE}/api/support/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || Object.values(data).flat()[0] || 'Failed to submit ticket');
  return data;
}

export async function getMySupportTickets(pagination = {}) {
  const qs = paginationQuery(pagination);
  const res = await authFetch(`${API_BASE}/api/support/mine/${qs}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get support tickets');
  return res.json();
}

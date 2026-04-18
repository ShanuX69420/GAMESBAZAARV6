const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

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

function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('gb_access_token');
}

function authHeaders() {
  const token = getToken();
  return {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
  };
}

export async function applyAsSeller(note) {
  const res = await fetch(`${API_BASE}/api/seller/apply/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ note }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Application failed');
  return data;
}

export async function getSellerStatus() {
  const res = await fetch(`${API_BASE}/api/seller/status/`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get seller status');
  return res.json();
}

export async function createListing(listingData) {
  const res = await fetch(`${API_BASE}/api/listings/`, {
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

export async function getMyListings() {
  const res = await fetch(`${API_BASE}/api/listings/mine/`, {
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

// ── Chat API ────────────────────────────────────────────────────────────────

export async function getConversations() {
  const res = await fetch(`${API_BASE}/api/chat/`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get conversations');
  return res.json();
}

export async function startConversation(userId, message = '') {
  const res = await fetch(`${API_BASE}/api/chat/start/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ user_id: userId, message }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to start conversation');
  return data;
}

export async function getConversation(id) {
  const res = await fetch(`${API_BASE}/api/chat/${id}/`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to get conversation');
  return res.json();
}

export async function sendMessage(conversationId, content) {
  const res = await fetch(`${API_BASE}/api/chat/${conversationId}/send/`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ content }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to send message');
  return data;
}

export async function getUnreadCount() {
  const res = await fetch(`${API_BASE}/api/chat/unread/`, {
    headers: authHeaders(),
  });
  if (!res.ok) return { unread_count: 0 };
  return res.json();
}


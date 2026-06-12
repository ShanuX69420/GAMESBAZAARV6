import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE } from '../lib/config';
import { getInboxWebSocketTicket } from '../lib/api';
import {
  encodeWebSocketTicket,
  buildTicketSubprotocols,
  sortConversationsByActivity,
  upsertConversation,
  applyPresenceToConversations,
} from '../lib/inbox';

function jsonResponse(data = {}, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(data),
  };
}

function convo(id, { lastMessageAt = null, updatedAt = '2026-06-01T00:00:00Z', otherUser = null, unread = 0 } = {}) {
  return {
    id,
    other_user: otherUser,
    last_message: lastMessageAt ? { content: 'hi', created_at: lastMessageAt } : null,
    unread_count: unread,
    updated_at: updatedAt,
  };
}

describe('inbox WebSocket ticket helpers', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ticket: 'abc', expires_in: 60 })));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('requests a user-scoped inbox ticket', async () => {
    const data = await getInboxWebSocketTicket();

    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE}/api/chat/inbox/ws-ticket/`,
      {
        credentials: 'include',
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      }
    );
    expect(data.ticket).toBe('abc');
  });

  it('surfaces ticket endpoint errors', async () => {
    fetch.mockResolvedValueOnce(jsonResponse({ error: 'Too many requests.' }, 429));
    await expect(getInboxWebSocketTicket()).rejects.toThrow('Too many requests.');
  });

  it('encodes tickets as unpadded base64url', () => {
    // Raw base64 of this input contains '+', '/' and '=' padding
    const ticket = '\xfb\xff\xbe-?';
    const encoded = encodeWebSocketTicket(ticket);
    expect(encoded).not.toMatch(/[+/=]/);
    expect(encoded).toBe(btoa(ticket).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''));
  });

  it('builds the chat subprotocol pair the backend expects', () => {
    const protocols = buildTicketSubprotocols('ticket-value');
    expect(protocols).toHaveLength(2);
    expect(protocols[0]).toBe('gb.chat');
    expect(protocols[1]).toBe(`gb.ticket.${encodeWebSocketTicket('ticket-value')}`);
  });
});

describe('inbox conversation list helpers', () => {
  it('sorts by last message time, falling back to updated_at', () => {
    const stale = convo(1, { updatedAt: '2026-06-10T00:00:00Z' });
    const recent = convo(2, { lastMessageAt: '2026-06-12T09:00:00Z' });
    const middle = convo(3, { lastMessageAt: '2026-06-11T00:00:00Z' });

    const sorted = sortConversationsByActivity([stale, middle, recent]);
    expect(sorted.map(c => c.id)).toEqual([2, 3, 1]);
  });

  it('upserts an updated conversation and reorders the list', () => {
    const a = convo(1, { lastMessageAt: '2026-06-12T08:00:00Z' });
    const b = convo(2, { lastMessageAt: '2026-06-12T09:00:00Z' });

    const updatedA = convo(1, { lastMessageAt: '2026-06-12T10:00:00Z', unread: 3 });
    const next = upsertConversation([b, a], updatedA);

    expect(next.map(c => c.id)).toEqual([1, 2]);
    expect(next[0].unread_count).toBe(3);
  });

  it('upserts a brand-new conversation to the top', () => {
    const existing = convo(1, { lastMessageAt: '2026-06-12T08:00:00Z' });
    const fresh = convo(9, { lastMessageAt: '2026-06-12T11:00:00Z' });

    const next = upsertConversation([existing], fresh);
    expect(next.map(c => c.id)).toEqual([9, 1]);
  });

  it('applies presence updates only to the matching partner', () => {
    const withSeller = convo(1, { otherUser: { id: 5, username: 'seller', last_active: null } });
    const withOther = convo(2, { otherUser: { id: 8, username: 'other', last_active: null } });

    const next = applyPresenceToConversations([withSeller, withOther], 5, '2026-06-12T12:00:00Z');
    expect(next[0].other_user.last_active).toBe('2026-06-12T12:00:00Z');
    expect(next[1].other_user.last_active).toBeNull();
  });

  it('returns the same array reference when no row matches a presence update', () => {
    const list = [convo(1, { otherUser: { id: 5, username: 'seller' } })];
    expect(applyPresenceToConversations(list, 999, '2026-06-12T12:00:00Z')).toBe(list);
  });
});

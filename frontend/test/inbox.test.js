import { describe, expect, it } from 'vitest';
import { sortConversationsByActivity } from '../lib/inbox';

function convo(id, { lastMessageAt = null, updatedAt = '2026-06-01T00:00:00Z', otherUser = null, unread = 0 } = {}) {
  return {
    id,
    other_user: otherUser,
    last_message: lastMessageAt ? { content: 'hi', created_at: lastMessageAt } : null,
    unread_count: unread,
    updated_at: updatedAt,
  };
}

describe('inbox conversation list helpers', () => {
  it('sorts by last message time, falling back to updated_at', () => {
    const stale = convo(1, { updatedAt: '2026-06-10T00:00:00Z' });
    const recent = convo(2, { lastMessageAt: '2026-06-12T09:00:00Z' });
    const middle = convo(3, { lastMessageAt: '2026-06-11T00:00:00Z' });

    const sorted = sortConversationsByActivity([stale, middle, recent]);
    expect(sorted.map(c => c.id)).toEqual([2, 3, 1]);
  });
});

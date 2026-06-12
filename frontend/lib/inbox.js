// Helpers for the inbox page's real-time conversation list.

const CHAT_SUBPROTOCOL = 'gb.chat';

export function encodeWebSocketTicket(ticket) {
  return btoa(ticket).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function buildTicketSubprotocols(ticket) {
  return [CHAT_SUBPROTOCOL, `gb.ticket.${encodeWebSocketTicket(ticket)}`];
}

export function sortConversationsByActivity(conversations) {
  return [...conversations].sort((a, b) => {
    const aDate = new Date(a.last_message?.created_at || a.updated_at).getTime();
    const bDate = new Date(b.last_message?.created_at || b.updated_at).getTime();
    return bDate - aDate;
  });
}

export function upsertConversation(conversations, updated) {
  const byId = new Map(conversations.map(convo => [convo.id, convo]));
  byId.set(updated.id, updated);
  return sortConversationsByActivity([...byId.values()]);
}

export function applyPresenceToConversations(conversations, userId, lastActive) {
  let changed = false;
  const next = conversations.map(convo => {
    if (convo.other_user?.id !== userId) return convo;
    changed = true;
    return { ...convo, other_user: { ...convo.other_user, last_active: lastActive } };
  });
  return changed ? next : conversations;
}

// Helpers for the messages page's conversation list.

export function sortConversationsByActivity(conversations) {
  return [...conversations].sort((a, b) => {
    const aDate = new Date(a.last_message?.created_at || a.updated_at).getTime();
    const bDate = new Date(b.last_message?.created_at || b.updated_at).getTime();
    return bDate - aDate;
  });
}

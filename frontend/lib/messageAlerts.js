// The "(3) GamesBazaar" unread counter in the browser tab title. Used by the
// navbar, which polls unread counts on every page.

const UNREAD_PREFIX_RE = /^\(\d{1,2}\+?\)\s/;

/**
 * Return `title` with the unread-chats counter applied: "(4) GamesBazaar".
 * Strips any existing counter first so repeated calls never stack prefixes;
 * a count of 0 just returns the bare title.
 */
export function withUnreadCount(title, count) {
  const base = title.replace(UNREAD_PREFIX_RE, '');
  if (!count || count <= 0) return base;
  return `(${count > 99 ? '99+' : count}) ${base}`;
}

// Find bare URLs inside user-written text (chat messages, seller
// instructions) so the UI can render them as clickable links.
// Returns the original string untouched when it contains no URL, otherwise
// a list of { text, href } parts where href is only set on URL parts.

const URL_PATTERN = /(?:https?:\/\/|www\.)[^\s<>"'`]+/gi;

const count = (s, ch) => s.split(ch).length - 1;

// Trailing sentence punctuation belongs to the surrounding text, not the
// URL ("watch https://youtu.be/abc." must not link the final dot). Closing
// brackets are only trimmed when unbalanced, so wiki-style /Foo_(bar) paths
// keep theirs.
function trimTrailingPunctuation(url) {
  for (;;) {
    const last = url[url.length - 1];
    const unbalanced =
      (last === ')' && count(url, ')') > count(url, '(')) ||
      (last === ']' && count(url, ']') > count(url, '['));
    if (!'.,!?;:'.includes(last) && !unbalanced) return url;
    url = url.slice(0, -1);
  }
}

export function splitUrls(text) {
  if (typeof text !== 'string' || !/https?:\/\/|www\./i.test(text)) return text;

  const parts = [];
  let cursor = 0;
  URL_PATTERN.lastIndex = 0;
  let match;
  while ((match = URL_PATTERN.exec(text)) !== null) {
    const url = trimTrailingPunctuation(match[0]);
    if (!url) continue;
    if (match.index > cursor) parts.push({ text: text.slice(cursor, match.index) });
    parts.push({
      text: url,
      href: /^www\./i.test(url) ? `https://${url}` : url,
    });
    cursor = match.index + url.length;
  }
  if (!parts.some(part => part.href)) return text;
  if (cursor < text.length) parts.push({ text: text.slice(cursor) });
  return parts;
}

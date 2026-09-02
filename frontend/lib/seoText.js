// Hand-written SEO copy (seo_body on the game-category pages, seoText on the
// section pages) is plain text with three conventions: blank lines separate
// paragraphs, "## " / "### " lines are headings, and [text](/path) is an
// inline link. Links are site-relative only ("/games/yalla-ludo/gift-cards",
// never a full URL) so the copy can tie related pages together — Google
// passes authority along the links and buyers can click through — without
// ever pointing off-site. Anything that isn't a site-relative path stays as
// literal text. The "### " headings double as the page's FAQ: each one is a
// question and the paragraphs that follow it (up to the next heading) are
// its answer, which is what extractSeoFaq feeds into the FAQPage JSON-LD.

const LINK_PATTERN = /\[([^[\]\n]+)\]\((\/(?!\/)[^\s()]*)\)/g;

export function splitSeoBlocks(text) {
  return String(text || '')
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean);
}

// Returns the string untouched when it has no links, otherwise a list of
// { text, href } parts where href is only set on link parts (same shape as
// lib/linkify's splitUrls).
export function parseInlineLinks(text) {
  const source = String(text || '');
  if (!source.includes('](')) return source;

  const parts = [];
  let cursor = 0;
  LINK_PATTERN.lastIndex = 0;
  let match;
  while ((match = LINK_PATTERN.exec(source)) !== null) {
    if (match.index > cursor) parts.push({ text: source.slice(cursor, match.index) });
    parts.push({ text: match[1], href: match[2] });
    cursor = match.index + match[0].length;
  }
  if (!parts.length) return source;
  if (cursor < source.length) parts.push({ text: source.slice(cursor) });
  return parts;
}

// The copy with link markup removed (only the link text kept), for places
// that must stay plain text such as FAQPage JSON-LD answers.
export function stripInlineLinks(text) {
  return String(text || '').replace(LINK_PATTERN, '$1');
}

// The FAQ pairs hidden in the copy: every "### " block is a question and the
// paragraphs after it, until the next heading of any level, are its answer.
// Questions without an answer are dropped and link markup is stripped from
// both sides, so the result can go straight into FAQPage JSON-LD (plain text)
// and always matches what the page visibly renders from the same blocks.
export function extractSeoFaq(blocks) {
  const faq = [];
  let current = null;
  for (const block of blocks || []) {
    if (block.startsWith('### ')) {
      current = { q: stripInlineLinks(block.slice(4).trim()), answers: [] };
      faq.push(current);
    } else if (block.startsWith('## ')) {
      current = null;
    } else if (current) {
      current.answers.push(stripInlineLinks(block));
    }
  }
  return faq
    .filter((item) => item.q && item.answers.length)
    .map((item) => ({ q: item.q, a: item.answers.join('\n\n') }));
}

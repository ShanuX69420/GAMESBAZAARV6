// Next's image optimizer, addressed directly.
//
// `next/image` prints the same optimizer URL three times per picture — `src`
// plus a 1x/2x `srcSet` — which is about 530 bytes of markup for a 40x40 game
// icon. On a list page with 400 rows that alone was ~150 KB of HTML, most of
// why /keys shipped 716 KB (2026-09-07). The rows are a fixed 40x40 with no
// responsive sizes, so one 2x variant is all any screen ever needs and a plain
// <img> can carry it.
//
// This builds the exact URL `next/image` would have requested, so nothing about
// how the icons are served changes: same optimizer, same `Cache-Control`, and
// the same cache entries nginx's img_cache already holds (deploy/nginx).
// `width` must be one of next.config's imageSizes/deviceSizes and `quality` one
// of its allowed qualities, or the optimizer answers 400.
const ICON_WIDTH = 96;   // 2x of the 40px box, from the default imageSizes
const ICON_QUALITY = 75; // Next's default quality

export function optimizedImageUrl(src, { width = ICON_WIDTH, quality = ICON_QUALITY } = {}) {
  if (!src) return '';
  return `/_next/image?url=${encodeURIComponent(src)}&w=${width}&q=${quality}`;
}

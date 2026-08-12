// Sizing maths for the sitewide review marquee (components/SiteReviews.js).
//
// The marquee is two identical copies of the same row, sliding left. When the
// loop resets, ONE copy is all that covers the screen — so a copy that is
// narrower than the viewport runs out mid-cycle and leaves a visible blank gap
// before it wraps. (Checking that BOTH copies together beat the viewport is the
// wrong test and passes while looking broken.)
//
// With too few reviews to fill a copy, the list is repeated until it does.

// Cards are 300px wide with a 16px gap, so 14 of them span ~4400px — enough for
// a 4K screen.
export const MIN_CARDS_PER_COPY = 14;

// Seconds each card spends crossing its own width. Applied to the RENDERED
// cards, so a repeated short list scrolls at the same speed as a full one.
export const SECONDS_PER_CARD = 6;

export function repeatToFillLoop(items, minLength = MIN_CARDS_PER_COPY) {
  if (!Array.isArray(items) || items.length === 0) return [];
  const repeats = Math.ceil(minLength / items.length);
  return Array.from({ length: repeats }, () => items).flat();
}

export function marqueeDuration(cardCount) {
  return `${cardCount * SECONDS_PER_CARD}s`;
}

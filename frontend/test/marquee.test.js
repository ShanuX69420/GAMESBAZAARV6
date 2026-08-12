import { describe, expect, it } from 'vitest';
import {
  MIN_CARDS_PER_COPY,
  SECONDS_PER_CARD,
  marqueeDuration,
  repeatToFillLoop,
} from '../lib/marquee';

// Card width + gap from reviews.css. One copy of the row has to out-span the
// widest screen the site is viewed on, or the marquee runs dry before it loops.
const CARD_WIDTH_PX = 300;
const CARD_GAP_PX = 16;
const WIDEST_SCREEN_PX = 3840;

function copyWidth(cardCount) {
  return cardCount * CARD_WIDTH_PX + (cardCount - 1) * CARD_GAP_PX;
}

describe('review marquee sizing', () => {
  it('pads a short review list until one copy outruns a 4K screen', () => {
    // Three reviews is 932px of cards — it used to leave a visible gap on
    // every wrap, on every screen size.
    const cards = repeatToFillLoop([{ id: 1 }, { id: 2 }, { id: 3 }]);

    expect(cards.length).toBeGreaterThanOrEqual(MIN_CARDS_PER_COPY);
    expect(copyWidth(cards.length)).toBeGreaterThan(WIDEST_SCREEN_PX);
  });

  it('leaves a list that is already long enough alone', () => {
    const reviews = Array.from({ length: 19 }, (_, i) => ({ id: i }));

    expect(repeatToFillLoop(reviews)).toHaveLength(19);
  });

  it('covers the screen at every review count the strip will render', () => {
    for (let count = 3; count <= 20; count += 1) {
      const reviews = Array.from({ length: count }, (_, i) => ({ id: i }));
      const cards = repeatToFillLoop(reviews);

      expect(copyWidth(cards.length)).toBeGreaterThan(WIDEST_SCREEN_PX);
    }
  });

  it('repeats whole copies of the list so the loop never cuts mid-set', () => {
    const reviews = [{ id: 1 }, { id: 2 }, { id: 3 }];

    const cards = repeatToFillLoop(reviews);

    expect(cards.length % reviews.length).toBe(0);
    expect(cards.slice(0, 3)).toEqual(reviews);
  });

  it('never loops forever on an empty list', () => {
    expect(repeatToFillLoop([])).toEqual([]);
    expect(repeatToFillLoop(undefined)).toEqual([]);
  });

  it('scrolls at one speed however many reviews there are', () => {
    // Duration tracks the RENDERED cards, so padding a short list out does not
    // make it race.
    expect(marqueeDuration(15)).toBe(`${15 * SECONDS_PER_CARD}s`);
    expect(marqueeDuration(19)).toBe(`${19 * SECONDS_PER_CARD}s`);
  });
});

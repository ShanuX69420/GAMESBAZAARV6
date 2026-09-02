import { describe, expect, it } from 'vitest';
import retiredByDestination from '../lib/retiredListings.json';
import { retiredListingCount, retiredListingRedirect } from '../lib/retiredListings';

describe('retired listing redirects', () => {
  it('sends deleted top-up listings to the same game\'s gift-card page', () => {
    // Free Fire "Monthly Membership (MENA)" and Mobile Legends "5 Diamonds
    // (Indonesia)" — direct top-ups deleted 2026-09-02.
    expect(retiredListingRedirect(30395)).toBe('/games/free-fire/gift-cards');
    expect(retiredListingRedirect('30395')).toBe('/games/free-fire/gift-cards');
    expect(retiredListingRedirect(' 30395 ')).toBe('/games/free-fire/gift-cards');
    expect(retiredListingRedirect(29656)).toBe('/games/mobile-legends-bang-bang/gift-cards');
  });

  it('sends deleted offline-activation listings to the game\'s keys page', () => {
    // Elder Scrolls IV offline activation, deleted with the category 2026-08-23.
    expect(retiredListingRedirect(30545)).toBe('/games/elder-scrolls/keys');
  });

  it('sends listings of fully retired brands to the gift-cards section', () => {
    // Wild Rift "10850 WC (Turkiye)" — the whole brand was retired.
    expect(retiredListingRedirect(35805)).toBe('/gift-cards');
  });

  it('ignores ids that were never retired', () => {
    expect(retiredListingRedirect(1)).toBeNull();
    expect(retiredListingRedirect('')).toBeNull();
    expect(retiredListingRedirect(undefined)).toBeNull();
    expect(retiredListingRedirect('abc')).toBeNull();
  });

  it('covers every deleted listing exactly once with a site-relative target', () => {
    const allIds = Object.values(retiredByDestination).flat();
    expect(allIds).toHaveLength(1411);
    expect(new Set(allIds).size).toBe(allIds.length);
    expect(retiredListingCount()).toBe(1411);
    for (const destination of Object.keys(retiredByDestination)) {
      expect(destination).toMatch(/^\/(gift-cards|keys|games\/[a-z0-9-]+\/[a-z0-9-]+)$/);
    }
  });
});

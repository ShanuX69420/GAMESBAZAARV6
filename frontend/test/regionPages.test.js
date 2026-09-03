import { describe, expect, it } from 'vitest';
import {
  brandPagePath,
  regionPageHeading,
  regionPagePath,
  regionSwitchTarget,
  stockedRegionPages,
} from '../lib/regionPages';

const regionPages = [
  { region: 'usa', label: 'USA', path: '/games/playstation/gift-cards/usa', listing_count: 18 },
  { region: 'united-kingdom', label: 'United Kingdom', path: '/games/playstation/gift-cards/united-kingdom', listing_count: 9 },
  { region: 'turkiye', label: 'Turkiye', path: '/games/playstation/gift-cards/turkiye', listing_count: 0 },
];

describe('region page helpers', () => {
  it('builds encoded region and brand paths', () => {
    expect(regionPagePath({ gameSlug: 'google play', categorySlug: 'gift-cards', region: 'saudi-arabia' }))
      .toBe('/games/google%20play/gift-cards/saudi-arabia');
    expect(brandPagePath({ gameSlug: 'valorant', categorySlug: 'vp' })).toBe('/games/valorant/vp');
  });

  it('links only to region pages with stock', () => {
    expect(stockedRegionPages(regionPages).map((page) => page.region)).toEqual(['usa', 'united-kingdom']);
    expect(stockedRegionPages(undefined)).toEqual([]);
  });

  it('sends a changed Region dropdown to the sibling region page when there is one', () => {
    expect(regionSwitchTarget({
      gameSlug: 'playstation', categorySlug: 'gift-cards', regionPages, value: 'united-kingdom',
    })).toBe('/games/playstation/gift-cards/united-kingdom');
    // An empty allow-listed region still has its own page (it is noindexed,
    // not gone), so the dropdown may land there.
    expect(regionSwitchTarget({
      gameSlug: 'playstation', categorySlug: 'gift-cards', regionPages, value: 'turkiye',
    })).toBe('/games/playstation/gift-cards/turkiye');
  });

  it('falls back to the pre-filtered brand page for regions off the allow-list', () => {
    expect(regionSwitchTarget({
      gameSlug: 'playstation', categorySlug: 'gift-cards', regionPages, value: 'japan',
    })).toBe('/games/playstation/gift-cards?region=japan');
    expect(regionSwitchTarget({
      gameSlug: 'playstation', categorySlug: 'gift-cards', regionPages, value: '',
    })).toBe('/games/playstation/gift-cards');
  });

  it('names the page like the option tiles do', () => {
    expect(regionPageHeading({ gameName: 'PlayStation', categoryName: 'Gift Cards', regionLabel: 'USA' }))
      .toBe('PlayStation Gift Cards (USA)');
  });
});

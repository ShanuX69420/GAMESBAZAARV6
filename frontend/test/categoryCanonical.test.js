import { describe, expect, it } from 'vitest';
import { canonicalCategoryPath } from '../lib/marketplaceUrls';

describe('canonicalCategoryPath', () => {
  const renamed = { category: { slug: 'robux', name: 'Robux' } };

  it("sends the category's own slug to the buyer-facing one", () => {
    expect(canonicalCategoryPath({
      gameSlug: 'roblox', requestedSlug: 'currency', data: renamed, query: {},
    })).toBe('/games/roblox/robux');
  });

  it('keeps the query string on the way', () => {
    expect(canonicalCategoryPath({
      gameSlug: 'roblox', requestedSlug: 'currency', data: renamed,
      query: { option: '1000 Robux', region: 'global', empty: '', filter_3: ['a', 'b'] },
    })).toBe('/games/roblox/robux?option=1000+Robux&region=global&filter_3=a&filter_3=b');
  });

  it('does nothing when the request already uses the canonical slug', () => {
    expect(canonicalCategoryPath({
      gameSlug: 'roblox', requestedSlug: 'robux', data: renamed, query: {},
    })).toBeNull();
  });

  it('does nothing for pages that were never renamed', () => {
    expect(canonicalCategoryPath({
      gameSlug: 'elden-ring', requestedSlug: 'keys', data: { category: { slug: 'keys' } }, query: {},
    })).toBeNull();
  });

  it('keeps the region segment when a region page is reached by the old slug', () => {
    expect(canonicalCategoryPath({
      gameSlug: 'roblox', requestedSlug: 'currency', data: renamed, query: { option: '3' },
      regionSlug: 'united-kingdom',
    })).toBe('/games/roblox/robux/united-kingdom?option=3');
    expect(canonicalCategoryPath({
      gameSlug: 'roblox', requestedSlug: 'robux', data: renamed, query: {}, regionSlug: 'usa',
    })).toBeNull();
  });

  it('does nothing without data to decide with', () => {
    expect(canonicalCategoryPath({ gameSlug: 'roblox', requestedSlug: 'currency', data: null, query: {} })).toBeNull();
  });
});

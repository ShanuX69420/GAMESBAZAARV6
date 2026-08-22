import { describe, expect, it } from 'vitest';
import {
  buildGameCategoryListingUrl,
  buildSellerListingsPath,
  buildSellerProfilePath,
} from '../lib/marketplaceUrls';

describe('marketplace URL helpers', () => {
  it('builds encoded game category listing API URLs', () => {
    const url = buildGameCategoryListingUrl({
      apiBase: 'https://api.example.test/',
      gameSlug: 'test game',
      categorySlug: 'accounts',
      limit: 48,
      offset: 96,
      filters: {
        12: 'Gold & Platinum',
        13: '',
      },
      instantOnly: true,
      search: 'prime vandal',
    });

    expect(url).toBe(
      'https://api.example.test/api/games/test%20game/accounts/?limit=48&offset=96&filter_12=Gold+%26+Platinum&instant_delivery=true&search=prime+vandal'
    );
  });

  it('carries ad-landing method/region params onto listing API URLs', () => {
    const url = buildGameCategoryListingUrl({
      apiBase: 'https://api.example.test',
      gameSlug: 'elden-ring',
      categorySlug: 'keys',
      limit: 48,
      offset: 0,
      method: 'as-a-gift',
      region: 'pakistan',
    });

    expect(url).toBe(
      'https://api.example.test/api/games/elden-ring/keys/?limit=48&offset=0&method=as-a-gift&region=pakistan'
    );
  });

  it('builds encoded game category paths', () => {
    expect(
      buildSellerListingsPath({
        gameSlug: 'test-game',
        categorySlug: 'accounts',
      })
    ).toBe('/games/test-game/accounts');
  });

  it('builds encoded seller profile paths', () => {
    expect(buildSellerProfilePath('seller+pk@example.com')).toBe('/seller/seller%2Bpk%40example.com');
  });
});

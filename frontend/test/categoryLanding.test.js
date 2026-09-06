import { describe, expect, it } from 'vitest';
import { landingParamsFromSearch } from '../lib/categoryLanding';

describe('landingParamsFromSearch', () => {
  it('is null for a bare URL, so the cached page is used as is', () => {
    expect(landingParamsFromSearch('')).toBeNull();
    expect(landingParamsFromSearch(undefined)).toBeNull();
    expect(landingParamsFromSearch('?limit=48&sort=newest')).toBeNull();
    expect(landingParamsFromSearch('?option=&method=%20')).toBeNull();
  });

  it('reads a shared option link', () => {
    expect(landingParamsFromSearch('?option=1000+Robux')).toEqual({
      option: '1000 Robux', method: '', region: '',
    });
  });

  it('reads an ad landing from /keys', () => {
    expect(landingParamsFromSearch('?method=digital-key&region=global')).toEqual({
      option: '', method: 'digital-key', region: 'global',
    });
  });
});

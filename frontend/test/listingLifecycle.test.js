import { describe, expect, it } from 'vitest';
import {
  listingAlternatives,
  listingBrowsePath,
  listingIsOutOfStock,
  listingLifecycle,
} from '../lib/listingLifecycle';

describe('listingLifecycle', () => {
  it('reads the state the backend decided', () => {
    expect(listingLifecycle({ status: 'active', lifecycle: { state: 'active' } }))
      .toEqual({ state: 'active', redirectTo: null });
    expect(listingLifecycle({ status: 'inactive', lifecycle: { state: 'paused', browse_path: '/games/steam/gift-cards' } }))
      .toEqual({ state: 'paused', redirectTo: null });
    expect(listingLifecycle({ id: 5, status: 'retired', lifecycle: { state: 'gone', reason: 'expired', redirect_to: '/games/steam/keys' } }))
      .toEqual({ state: 'gone', redirectTo: '/games/steam/keys' });
    expect(listingLifecycle({ id: 5, status: 'retired', lifecycle: { state: 'unindexed', redirect_to: null } }))
      .toEqual({ state: 'unindexed', redirectTo: null });
  });

  it('never redirects off-site or nowhere', () => {
    expect(listingLifecycle({ status: 'retired', lifecycle: { state: 'gone', redirect_to: 'https://evil.example/' } }))
      .toEqual({ state: 'unindexed', redirectTo: null });
    expect(listingLifecycle({ status: 'retired', lifecycle: { state: 'gone', redirect_to: '//evil.example/' } }))
      .toEqual({ state: 'unindexed', redirectTo: null });
    expect(listingLifecycle({ status: 'retired', lifecycle: { state: 'gone', redirect_to: '' } }))
      .toEqual({ state: 'unindexed', redirectTo: null });
  });

  it('falls back on status for payloads cached before lifecycle existed', () => {
    expect(listingLifecycle({ status: 'active', title: 'Old cached' }))
      .toEqual({ state: 'active', redirectTo: null });
    expect(listingLifecycle({ status: 'sold', title: 'Old cached' }))
      .toEqual({ state: 'paused', redirectTo: null });
    expect(listingLifecycle({ status: 'retired' }))
      .toEqual({ state: 'unindexed', redirectTo: null });
  });

  it('treats nothing as missing', () => {
    expect(listingLifecycle(null)).toEqual({ state: 'missing', redirectTo: null });
    expect(listingLifecycle(undefined)).toEqual({ state: 'missing', redirectTo: null });
    expect(listingLifecycle('nope')).toEqual({ state: 'missing', redirectTo: null });
  });
});

describe('out-of-stock helpers', () => {
  const paused = {
    status: 'inactive',
    lifecycle: {
      state: 'paused',
      browse_path: '/games/steam/gift-cards',
      alternatives: [
        { id: 12, title: '10 USD (USA)', price: '3050.00', option_name: '10 USD (USA)' },
        { id: 'x', title: 'broken' },
        null,
      ],
    },
  };

  it('knows when the page renders without a buy button', () => {
    expect(listingIsOutOfStock(paused)).toBe(true);
    expect(listingIsOutOfStock({ status: 'active', lifecycle: { state: 'active' } })).toBe(false);
  });

  it('keeps only usable alternatives', () => {
    expect(listingAlternatives(paused)).toEqual([
      { id: 12, title: '10 USD (USA)', price: '3050.00', option_name: '10 USD (USA)' },
    ]);
    expect(listingAlternatives({ lifecycle: { state: 'active' } })).toEqual([]);
    expect(listingAlternatives(null)).toEqual([]);
  });

  it('only offers site-relative browse links', () => {
    expect(listingBrowsePath(paused)).toBe('/games/steam/gift-cards');
    expect(listingBrowsePath({ lifecycle: { state: 'paused', browse_path: 'https://x.example' } })).toBeNull();
    expect(listingBrowsePath({})).toBeNull();
  });
});

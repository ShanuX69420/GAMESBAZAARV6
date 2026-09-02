import { describe, expect, it } from 'vitest';
import {
  SEO_TITLE_MAX_LENGTH,
  listingBreadcrumbs,
  listingDisplayName,
  listingPageTitle,
  listingSchemaBreadcrumbs,
  singularize,
} from '../lib/listingSeo.js';

describe('listingDisplayName', () => {
  it('prefixes the brand and appends the product word on gift-card listings', () => {
    // Thirteen brands share "50 USD (USA)" — the brand is what makes them distinct.
    expect(listingDisplayName({
      title: '5 USD (Argentina)',
      listing_mode: 'offer',
      game_name: 'Steam',
      category_name: 'Gift Cards',
      filter_display: { Region: 'Argentina' },
    })).toBe('Steam 5 USD (Argentina) Gift Card');

    expect(listingDisplayName({
      title: '10 USD (USA)',
      listing_mode: 'offer',
      game_name: 'PlayStation',
      category_name: 'Gift Cards',
    })).toBe('PlayStation 10 USD (USA) Gift Card');
  });

  it('does not repeat a category word the title already carries', () => {
    expect(listingDisplayName({
      title: '60 UC',
      listing_mode: 'offer',
      game_name: 'PUBG Mobile',
      category_name: 'UC',
      filter_display: { Type: 'UC' },
    })).toBe('PUBG Mobile 60 UC');

    expect(listingDisplayName({
      title: '13 Diamonds',
      listing_mode: 'offer',
      game_name: 'Free Fire',
      category_name: 'Diamonds',
      filter_display: { Region: 'Pakistan' },
    })).toBe('Free Fire 13 Diamonds');

    expect(listingDisplayName({
      title: '1000 VP',
      listing_mode: 'offer',
      game_name: 'Valorant',
      category_name: 'VP',
    })).toBe('Valorant 1000 VP');
  });

  it('leaves the category label off pages that sell several product types', () => {
    // PUBG's UC page also lists WOW Coins under a Type dropdown; "UC" would be wrong there.
    expect(listingDisplayName({
      title: '60 WOW Coins',
      listing_mode: 'offer',
      game_name: 'PUBG Mobile',
      category_name: 'UC',
      filter_display: { Type: 'WOW Coins' },
    })).toBe('PUBG Mobile 60 WOW Coins');
  });

  it('does not repeat a game name the title already carries', () => {
    expect(listingDisplayName({
      title: 'PUBG Mobile 325 UC',
      listing_mode: 'offer',
      game_name: 'PUBG Mobile',
      category_name: 'UC',
    })).toBe('PUBG Mobile 325 UC');

    expect(listingDisplayName({
      title: 'Game Pass Ultimate 1 Month',
      listing_mode: 'offer',
      game_name: 'Xbox',
      category_name: 'Game Pass',
    })).toBe('Xbox Game Pass Ultimate 1 Month');
  });

  it('leaves standard and currency listings exactly as written', () => {
    expect(listingDisplayName({
      title: 'Elden Ring (PS4/PS5) - Rent 30 Days',
      listing_mode: 'standard',
      game_name: 'Elden Ring',
      category_name: 'Rentals',
    })).toBe('Elden Ring (PS4/PS5) - Rent 30 Days');

    expect(listingDisplayName({
      title: 'Far Cry 3 Classic Edition (PS4/PS5) - Rent 7 Days',
      listing_mode: 'standard',
      game_name: 'Farcry',
      category_name: 'Rentals',
    })).toBe('Far Cry 3 Classic Edition (PS4/PS5) - Rent 7 Days');

    expect(listingDisplayName({
      title: 'Robux',
      listing_mode: 'currency',
      game_name: 'Roblox',
      category_name: 'Robux',
    })).toBe('Robux');
  });

  it('collapses whitespace and survives missing fields', () => {
    expect(listingDisplayName({ title: '  5 USD   (Argentina) ', listing_mode: 'offer' }))
      .toBe('5 USD (Argentina)');
    expect(listingDisplayName({ title: '' })).toBe('');
    expect(listingDisplayName(null)).toBe('');
  });
});

describe('singularize', () => {
  it('drops a plural s but not a double s or a short code', () => {
    expect(singularize('Gift Cards')).toBe('Gift Card');
    expect(singularize('Top Ups')).toBe('Top Up');
    expect(singularize('Game Pass')).toBe('Game Pass');
    expect(singularize('Robux')).toBe('Robux');
    expect(singularize('UC')).toBe('UC');
    expect(singularize('Subscription')).toBe('Subscription');
  });
});

describe('listingPageTitle', () => {
  it('keeps the site-name template while the title fits the visible budget', () => {
    const result = listingPageTitle({ name: 'PUBG Mobile 60 UC', price: 'PKR 290' });
    expect(result).toEqual({ title: 'PUBG Mobile 60 UC - PKR 290', absolute: false });
    expect(`${result.title} | GamesBazaar`.length).toBeLessThanOrEqual(SEO_TITLE_MAX_LENGTH);
  });

  it('drops the site-name suffix when the templated title would run long', () => {
    const result = listingPageTitle({
      name: 'PlayStation 100 USD (Argentina) Gift Card',
      price: 'PKR 35,200',
    });
    expect(result.absolute).toBe(true);
    expect(result.title).toBe('PlayStation 100 USD (Argentina) Gift Card - PKR 35,200');
  });

  it('omits the price part when there is no price', () => {
    expect(listingPageTitle({ name: 'Steam 5 USD Gift Card', price: '' }))
      .toEqual({ title: 'Steam 5 USD Gift Card', absolute: false });
  });
});

describe('listingBreadcrumbs', () => {
  it('links Home, the game and the category page the listing lives on', () => {
    expect(listingBreadcrumbs({
      game_name: 'Valorant',
      game_slug: 'valorant',
      category_name: 'Accounts',
      category_slug: 'accounts',
    })).toEqual([
      { name: 'Home', path: '/' },
      { name: 'Valorant', path: '/games/valorant' },
      { name: 'Accounts', path: '/games/valorant/accounts' },
    ]);
  });

  it('uses the renamed category slug the site URL uses', () => {
    // A per-game rename ("Top Ups" shown as "Subscriptions") changes the
    // URL; the API sends the buyer-facing slug and the crumb must follow it.
    const crumbs = listingBreadcrumbs({
      game_name: 'PlayStation',
      game_slug: 'playstation',
      category_name: 'Subscriptions',
      category_slug: 'subscriptions',
    });
    expect(crumbs[2]).toEqual({ name: 'Subscriptions', path: '/games/playstation/subscriptions' });
  });

  it('shows names as plain text when a cached payload has no slugs', () => {
    expect(listingBreadcrumbs({ game_name: 'Valorant', category_name: 'Accounts' })).toEqual([
      { name: 'Home', path: '/' },
      { name: 'Valorant', path: null },
      { name: 'Accounts', path: null },
    ]);
    // A game slug alone links the game but never a half-built category URL.
    const partial = listingBreadcrumbs({
      game_name: 'Valorant', game_slug: 'valorant', category_name: 'Accounts',
    });
    expect(partial[1].path).toBe('/games/valorant');
    expect(partial[2].path).toBeNull();
  });

  it('never builds a link out of a slug that is not a slug', () => {
    const crumbs = listingBreadcrumbs({
      game_name: 'Valorant', game_slug: '../admin', category_name: 'Accounts', category_slug: 'accounts',
    });
    expect(crumbs[1].path).toBeNull();
    expect(crumbs[2].path).toBeNull();
  });

  it('is just Home for an empty listing', () => {
    expect(listingBreadcrumbs(null)).toEqual([{ name: 'Home', path: '/' }]);
  });
});

describe('listingSchemaBreadcrumbs', () => {
  it('names the category page after its own title and leaves the redirecting game URL out', () => {
    expect(listingSchemaBreadcrumbs({
      game_name: 'Elden Ring',
      game_slug: 'elden-ring',
      category_name: 'Keys',
      category_slug: 'keys',
    })).toEqual([
      { name: 'Home', path: '/' },
      { name: 'Elden Ring Keys', path: '/games/elden-ring/keys' },
    ]);
  });

  it('is null until the payload carries both page slugs', () => {
    expect(listingSchemaBreadcrumbs({ game_name: 'Elden Ring', category_name: 'Keys' })).toBeNull();
    expect(listingSchemaBreadcrumbs({
      game_name: 'Elden Ring', game_slug: 'elden-ring', category_name: 'Keys',
    })).toBeNull();
    expect(listingSchemaBreadcrumbs(null)).toBeNull();
  });
});

import { describe, expect, it } from 'vitest';
import { sectionParamsFromSearch, sectionUrl } from '../lib/sectionLanding';
import { optimizedImageUrl } from '../lib/imageUrl';

describe('sectionParamsFromSearch', () => {
  it('is null for a bare URL, so the cached page is used as is', () => {
    expect(sectionParamsFromSearch('')).toBeNull();
    expect(sectionParamsFromSearch(undefined)).toBeNull();
    expect(sectionParamsFromSearch('?utm_source=hxb')).toBeNull();
    expect(sectionParamsFromSearch('?method=%20&region=')).toBeNull();
  });

  it('reads an ad landing on a filtered section', () => {
    expect(sectionParamsFromSearch('?method=digital-key&region=global')).toEqual({
      method: 'digital-key', region: 'global', sort: '',
    });
  });

  it('reads a sort on its own', () => {
    expect(sectionParamsFromSearch('?sort=price_asc')).toEqual({
      method: '', region: '', sort: 'price_asc',
    });
  });
});

describe('sectionUrl', () => {
  it('drops back to the bare path when nothing is selected', () => {
    expect(sectionUrl('/keys', { method: '', region: '', sort: '' })).toBe('/keys');
    expect(sectionUrl('/keys')).toBe('/keys');
  });

  it('carries only the dropdowns that are set', () => {
    expect(sectionUrl('/keys', { method: 'as-a-gift', region: '', sort: 'price_asc' }))
      .toBe('/keys?method=as-a-gift&sort=price_asc');
  });

  it('round-trips through sectionParamsFromSearch', () => {
    const selection = { method: 'digital-key', region: 'global', sort: 'listings' };
    const url = sectionUrl('/keys', selection);
    expect(sectionParamsFromSearch(url.slice(url.indexOf('?')))).toEqual(selection);
  });
});

describe('optimizedImageUrl', () => {
  // The width and quality have to stay values next.config allows, or the
  // optimizer answers 400 and every game icon breaks at once.
  it('asks the optimizer for one 2x variant of a 40px icon', () => {
    expect(optimizedImageUrl('https://media.gamesbazaar.pk/r2/game_icons/a.webp')).toBe(
      '/_next/image?url=https%3A%2F%2Fmedia.gamesbazaar.pk%2Fr2%2Fgame_icons%2Fa.webp&w=96&q=75',
    );
  });

  it('is empty for a game with no icon, so nothing requests /_next/image?url=', () => {
    expect(optimizedImageUrl('')).toBe('');
    expect(optimizedImageUrl(null)).toBe('');
  });
});

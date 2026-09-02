import { describe, expect, it } from 'vitest';
import { parseInlineLinks, splitSeoBlocks, stripInlineLinks } from '../lib/seoText';

describe('SEO copy inline links', () => {
  it('leaves copy without links untouched', () => {
    expect(parseInlineLinks('Plain sentence.')).toBe('Plain sentence.');
    expect(parseInlineLinks('')).toBe('');
    expect(parseInlineLinks(null)).toBe('');
  });

  it('splits [text](/path) into link parts and keeps the surrounding text', () => {
    expect(parseInlineLinks(
      'Send them a code from our [Yalla Ludo gift-cards page](/games/yalla-ludo/gift-cards) instead.',
    )).toEqual([
      { text: 'Send them a code from our ' },
      { text: 'Yalla Ludo gift-cards page', href: '/games/yalla-ludo/gift-cards' },
      { text: ' instead.' },
    ]);
  });

  it('handles several links and a link at either end', () => {
    expect(parseInlineLinks('[A](/a) and [B](/b?x=1#y)')).toEqual([
      { text: 'A', href: '/a' },
      { text: ' and ' },
      { text: 'B', href: '/b?x=1#y' },
    ]);
  });

  it('only links site-relative paths, never full URLs or protocol-relative ones', () => {
    // Off-site links would leak authority (and could be abused); the copy is
    // hand-written so these stay visible as literal text to be fixed.
    expect(parseInlineLinks('see [x](https://example.com)')).toBe('see [x](https://example.com)');
    expect(parseInlineLinks('see [x](//example.com)')).toBe('see [x](//example.com)');
    expect(parseInlineLinks('see [x](games/foo)')).toBe('see [x](games/foo)');
  });

  it('strips markup for plain-text contexts such as JSON-LD', () => {
    expect(stripInlineLinks('Use our [Robux page](/games/roblox/robux) instead.'))
      .toBe('Use our Robux page instead.');
    expect(stripInlineLinks('no links')).toBe('no links');
  });

  it('splits blocks on blank lines and trims them', () => {
    expect(splitSeoBlocks('## Heading\n\nPara one.\n  \n\nPara two.\n')).toEqual([
      '## Heading', 'Para one.', 'Para two.',
    ]);
    expect(splitSeoBlocks('')).toEqual([]);
  });
});

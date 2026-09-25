import { describe, expect, it } from 'vitest';
import {
  extractSeoFaq, parseInlineLinks, parseSeoTable, splitSeoBlocks, stripInlineLinks,
} from '../lib/seoText';

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

describe('SEO copy FAQ extraction', () => {
  it('pairs each "### " question with the paragraph under it', () => {
    const blocks = splitSeoBlocks([
      '## How it works',
      'Intro paragraph that is not an answer.',
      '## PUBG UC FAQs',
      '### How fast is delivery?',
      'Most orders land within minutes.',
      '### Do I need my password?',
      'No. Only your Character ID.',
    ].join('\n\n'));
    expect(extractSeoFaq(blocks)).toEqual([
      { q: 'How fast is delivery?', a: 'Most orders land within minutes.' },
      { q: 'Do I need my password?', a: 'No. Only your Character ID.' },
    ]);
  });

  it('returns nothing for copy without questions', () => {
    expect(extractSeoFaq(splitSeoBlocks('## Heading\n\nJust a paragraph.'))).toEqual([]);
    expect(extractSeoFaq([])).toEqual([]);
    expect(extractSeoFaq(undefined)).toEqual([]);
  });

  it('keeps answers plain text and joins multi-paragraph answers', () => {
    // JSON-LD answers must not carry link markup; the page still renders the
    // links from the same blocks.
    const blocks = splitSeoBlocks([
      '### Where do vouchers redeem?',
      'On our [PUBG UC page](/games/pubg-mobile/uc) or Midasbuy.',
      'Either way the code is yours within minutes.',
    ].join('\n\n'));
    expect(extractSeoFaq(blocks)).toEqual([{
      q: 'Where do vouchers redeem?',
      a: 'On our PUBG UC page or Midasbuy.\n\nEither way the code is yours within minutes.',
    }]);
  });

  it('ends an answer at the next heading and drops questions with no answer', () => {
    const blocks = splitSeoBlocks([
      '### Answered?',
      'Yes.',
      '## Closing section',
      'This paragraph belongs to the section, not the question.',
      '### Unanswered?',
    ].join('\n\n'));
    expect(extractSeoFaq(blocks)).toEqual([{ q: 'Answered?', a: 'Yes.' }]);
  });
});

describe('SEO copy price tables', () => {
  const TABLE = [
    '| Pack | Price | Per Robux |',
    '|---|---|---|',
    '| 50 Robux (Global) | PKR 320 | PKR 6.40 |',
    '| 1,000 Robux (Global) | PKR 3,530 | PKR 3.53 |',
  ].join('\n');

  it('parses the API price table into header and rows', () => {
    expect(parseSeoTable(TABLE)).toEqual({
      head: ['Pack', 'Price', 'Per Robux'],
      rows: [
        ['50 Robux (Global)', 'PKR 320', 'PKR 6.40'],
        ['1,000 Robux (Global)', 'PKR 3,530', 'PKR 3.53'],
      ],
    });
  });

  it('stays a table block when split out of the surrounding copy', () => {
    const blocks = splitSeoBlocks(`## Robux to PKR price list\n\n${TABLE}\n\nPrices move daily.`);
    expect(blocks).toHaveLength(3);
    expect(parseSeoTable(blocks[1])?.rows).toHaveLength(2);
  });

  it('treats anything else as ordinary copy', () => {
    expect(parseSeoTable('A paragraph | with a pipe in it.')).toBeNull();
    expect(parseSeoTable('| lone row |')).toBeNull();
    expect(parseSeoTable('| a | b |\n| c | d |')).toBeNull(); // no divider
    expect(parseSeoTable('## Heading')).toBeNull();
    expect(parseSeoTable('')).toBeNull();
  });

  it('never puts a table into a FAQ answer', () => {
    const faq = extractSeoFaq(splitSeoBlocks(
      `### How much is 1,000 Robux in PKR?\n\nSee the list.\n\n${TABLE}`,
    ));
    expect(faq).toEqual([{ q: 'How much is 1,000 Robux in PKR?', a: 'See the list.' }]);
  });
});

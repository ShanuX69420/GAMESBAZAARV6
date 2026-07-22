import { describe, it, expect } from 'vitest';
import { splitUrls } from '@/lib/linkify';

describe('splitUrls', () => {
  it('returns plain text unchanged', () => {
    expect(splitUrls('just a normal message')).toBe('just a normal message');
    expect(splitUrls('')).toBe('');
    expect(splitUrls(null)).toBe(null);
    expect(splitUrls(undefined)).toBe(undefined);
  });

  it('ignores dots that are not URLs', () => {
    expect(splitUrls('version 2.0 is out. enjoy')).toBe('version 2.0 is out. enjoy');
  });

  it('links a URL in the middle of a sentence', () => {
    expect(splitUrls('watch https://youtu.be/abc123 for the steps')).toEqual([
      { text: 'watch ' },
      { text: 'https://youtu.be/abc123', href: 'https://youtu.be/abc123' },
      { text: ' for the steps' },
    ]);
  });

  it('links a URL at the start and end of the text', () => {
    expect(splitUrls('https://docs.google.com/doc/1')).toEqual([
      { text: 'https://docs.google.com/doc/1', href: 'https://docs.google.com/doc/1' },
    ]);
  });

  it('does not swallow trailing punctuation', () => {
    expect(splitUrls('read https://example.com/guide.')).toEqual([
      { text: 'read ' },
      { text: 'https://example.com/guide', href: 'https://example.com/guide' },
      { text: '.' },
    ]);
    expect(splitUrls('(see https://example.com/a)')).toEqual([
      { text: '(see ' },
      { text: 'https://example.com/a', href: 'https://example.com/a' },
      { text: ')' },
    ]);
  });

  it('keeps balanced parentheses that are part of the URL', () => {
    expect(splitUrls('https://en.wikipedia.org/wiki/Steam_(service)')).toEqual([
      {
        text: 'https://en.wikipedia.org/wiki/Steam_(service)',
        href: 'https://en.wikipedia.org/wiki/Steam_(service)',
      },
    ]);
  });

  it('prefixes https:// on bare www links', () => {
    expect(splitUrls('go to www.youtube.com/watch?v=abc')).toEqual([
      { text: 'go to ' },
      { text: 'www.youtube.com/watch?v=abc', href: 'https://www.youtube.com/watch?v=abc' },
    ]);
  });

  it('handles several URLs and newlines', () => {
    expect(
      splitUrls('Step 1: https://a.com\nStep 2: https://b.com, then confirm')
    ).toEqual([
      { text: 'Step 1: ' },
      { text: 'https://a.com', href: 'https://a.com' },
      { text: '\nStep 2: ' },
      { text: 'https://b.com', href: 'https://b.com' },
      { text: ', then confirm' },
    ]);
  });

  it('keeps query strings and fragments intact', () => {
    expect(splitUrls('https://youtube.com/watch?v=x&t=90s#top')).toEqual([
      { text: 'https://youtube.com/watch?v=x&t=90s#top', href: 'https://youtube.com/watch?v=x&t=90s#top' },
    ]);
  });
});

import { describe, expect, it } from 'vitest';
import { formatReviewDate } from '../lib/dates';

describe('formatReviewDate', () => {
  it('renders the Pakistan-time calendar day regardless of environment zone', () => {
    // 22:44 UTC = 03:44 next day in PKT. Without the pinned zone the server
    // (UTC) and a PK browser disagree on the day, which breaks hydration and
    // wipes the dark-mode attribute on <html>.
    expect(formatReviewDate('2026-08-15T22:44:01Z')).toBe('16 Aug 2026');
    expect(formatReviewDate('2026-08-16T03:44:01+05:00')).toBe('16 Aug 2026');
  });

  it('handles daytime dates and empty values', () => {
    expect(formatReviewDate('2026-08-20T10:00:00Z')).toBe('20 Aug 2026');
    expect(formatReviewDate('')).toBe('');
    expect(formatReviewDate(null)).toBe('');
  });
});

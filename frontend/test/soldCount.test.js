import { describe, expect, it } from 'vitest';
import { formatSoldCount } from '@/lib/soldCount';

describe('formatSoldCount', () => {
  it('hides zero, negative, and missing counts', () => {
    expect(formatSoldCount(0)).toBeNull();
    expect(formatSoldCount(-3)).toBeNull();
    expect(formatSoldCount(null)).toBeNull();
    expect(formatSoldCount(undefined)).toBeNull();
    expect(formatSoldCount('nope')).toBeNull();
  });

  it('labels real counts', () => {
    expect(formatSoldCount(1)).toBe('1 sold');
    expect(formatSoldCount('12')).toBe('12 sold');
    expect(formatSoldCount(1250)).toBe('1,250 sold');
  });
});

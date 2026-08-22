import { describe, expect, it } from 'vitest';
import { withUnreadCount } from '../lib/messageAlerts';

describe('withUnreadCount (tab title unread counter)', () => {
  it('prefixes the title with the unread count', () => {
    expect(withUnreadCount('GamesBazaar', 4)).toBe('(4) GamesBazaar');
  });

  it('returns the bare title when there is nothing unread', () => {
    expect(withUnreadCount('GamesBazaar', 0)).toBe('GamesBazaar');
    expect(withUnreadCount('GamesBazaar', null)).toBe('GamesBazaar');
    expect(withUnreadCount('GamesBazaar', undefined)).toBe('GamesBazaar');
  });

  it('replaces an existing counter instead of stacking prefixes', () => {
    expect(withUnreadCount('(3) GamesBazaar', 4)).toBe('(4) GamesBazaar');
    expect(withUnreadCount('(99+) GamesBazaar', 2)).toBe('(2) GamesBazaar');
  });

  it('strips the counter when unread drops back to zero', () => {
    expect(withUnreadCount('(7) GamesBazaar', 0)).toBe('GamesBazaar');
  });

  it('caps the display at 99+', () => {
    expect(withUnreadCount('GamesBazaar', 99)).toBe('(99) GamesBazaar');
    expect(withUnreadCount('GamesBazaar', 100)).toBe('(99+) GamesBazaar');
  });

  it('leaves titles that merely start with parenthesized text alone', () => {
    expect(withUnreadCount('(2026) Year in Review', 0)).toBe('(2026) Year in Review');
    expect(withUnreadCount('(beta) GamesBazaar', 0)).toBe('(beta) GamesBazaar');
  });
});

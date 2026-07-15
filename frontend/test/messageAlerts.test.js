import { describe, expect, it } from 'vitest';
import { withUnreadCount, nextSoundStamps } from '../lib/messageAlerts';

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

describe('nextSoundStamps (per-conversation sound cooldown)', () => {
  const MIN = 60 * 1000;

  it('allows the first ding for a conversation and stamps it', () => {
    expect(nextSoundStamps({}, 7, 1000)).toEqual({ 7: 1000 });
  });

  it('suppresses repeat dings from the same conversation inside the window', () => {
    const stamps = { 7: 1000 };
    expect(nextSoundStamps(stamps, 7, 1000 + 4 * MIN)).toBeNull();
  });

  it('allows the same conversation again after the window has passed', () => {
    const stamps = { 7: 1000 };
    const later = 1000 + 5 * MIN;
    expect(nextSoundStamps(stamps, 7, later)).toEqual({ 7: later });
  });

  it('lets a different conversation ding instantly during another chat cooldown', () => {
    const stamps = { 7: 1000 };
    expect(nextSoundStamps(stamps, 8, 2000)).toEqual({ 7: 1000, 8: 2000 });
  });

  it('prunes expired conversations so the map never grows unbounded', () => {
    const stamps = { 7: 1000, 8: 2000 };
    const later = 2000 + 6 * MIN;
    expect(nextSoundStamps(stamps, 9, later)).toEqual({ 9: later });
  });

  it('respects a custom cooldown length', () => {
    expect(nextSoundStamps({ 7: 1000 }, 7, 1500, 400)).toEqual({ 7: 1500 });
    expect(nextSoundStamps({ 7: 1000 }, 7, 1500, 2000)).toBeNull();
  });
});

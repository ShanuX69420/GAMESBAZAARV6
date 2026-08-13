import { describe, expect, it } from 'vitest';
import {
  loginHref,
  postLoginPath,
  safeNextPath,
  withNext,
} from '../lib/loginRedirect';

describe('login redirect helpers', () => {
  it('accepts same-site paths', () => {
    expect(safeNextPath('/listing/123')).toBe('/listing/123');
    expect(safeNextPath('/listing/123?buy=1&qty=2')).toBe('/listing/123?buy=1&qty=2');
  });

  it('rejects anything that could leave the site', () => {
    expect(safeNextPath('//evil.example')).toBeNull();
    expect(safeNextPath('/\\evil.example')).toBeNull();
    expect(safeNextPath('https://evil.example/listing/1')).toBeNull();
    expect(safeNextPath('listing/1')).toBeNull();
    expect(safeNextPath('/')).toBeNull();
    expect(safeNextPath(null)).toBeNull();
    expect(safeNextPath(undefined)).toBeNull();
  });

  it('builds login links that carry the destination', () => {
    expect(loginHref('/listing/123?buy=1')).toBe('/login?next=%2Flisting%2F123%3Fbuy%3D1');
    expect(loginHref(null)).toBe('/login');
    expect(loginHref('https://evil.example')).toBe('/login');
  });

  it('appends next to auth paths that already have a query', () => {
    expect(withNext('/verify-email?email=a%40b.pk', '/listing/9')).toBe(
      '/verify-email?email=a%40b.pk&next=%2Flisting%2F9'
    );
    expect(withNext('/register', null)).toBe('/register');
  });

  it('falls back to the usual landing page without a destination', () => {
    expect(postLoginPath('/listing/123', { is_seller: true })).toBe('/listing/123');
    expect(postLoginPath(null, { is_seller: true })).toBe('/dashboard');
    expect(postLoginPath(null, { is_seller: false })).toBe('/');
    expect(postLoginPath('//evil.example', null)).toBe('/');
  });
});

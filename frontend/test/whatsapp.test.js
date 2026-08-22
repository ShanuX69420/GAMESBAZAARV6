import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE } from '../lib/config';
import { openWhatsAppChat, waLink, WHATSAPP_NUMBER } from '../lib/whatsapp';

function jsonResponse(data = {}, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(data),
    headers: { get: () => null },
  };
}

describe('Buy on WhatsApp', () => {
  let openedWindow;

  beforeEach(() => {
    openedWindow = { closed: false, opener: 'site', location: { href: '' } };
    vi.stubGlobal('window', {
      open: vi.fn(() => openedWindow),
      location: { pathname: '/listing/5', href: '' },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ref: 'WA-TEST12' })));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('builds plain and prefilled chat links', () => {
    expect(waLink()).toBe(`https://wa.me/${WHATSAPP_NUMBER}`);
    expect(waLink('Hi there')).toBe(`https://wa.me/${WHATSAPP_NUMBER}?text=Hi%20there`);
  });

  it('records the click, then opens the chat with the reference code', async () => {
    const listing = { id: 5, title: 'Elden Ring Key', price: '8500' };
    await openWhatsAppChat({ listing, quantity: 2 });

    // The tab must be claimed synchronously (popup blockers) and detached.
    expect(window.open).toHaveBeenCalledWith('about:blank', '_blank');
    expect(openedWindow.opener).toBeNull();

    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE}/api/whatsapp/checkout/`,
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({ page: '/listing/5', listing_id: 5, quantity: 2 }),
      })
    );

    expect(openedWindow.location.href).toContain(`https://wa.me/${WHATSAPP_NUMBER}?text=`);
    const message = decodeURIComponent(openedWindow.location.href.split('?text=')[1]);
    expect(message).toContain('Elden Ring Key x2');
    expect(message).toContain('PKR 17,000');
    expect(message).toContain('(Ref: WA-TEST12)');
  });

  it('still lands in WhatsApp (untracked) when the API call fails', async () => {
    fetch.mockRejectedValue(new Error('network down'));
    await openWhatsAppChat({ listing: { id: 5, title: 'Elden Ring Key', price: '8500' } });

    expect(openedWindow.location.href).toContain(`https://wa.me/${WHATSAPP_NUMBER}?text=`);
    expect(openedWindow.location.href).not.toContain('Ref');
  });

  it('falls back to same-tab navigation when the popup is blocked', async () => {
    window.open.mockReturnValue(null);
    await openWhatsAppChat({ page: '/steam' });

    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE}/api/whatsapp/checkout/`,
      expect.objectContaining({ body: JSON.stringify({ page: '/steam' }) })
    );
    expect(window.location.href).toContain(`https://wa.me/${WHATSAPP_NUMBER}?text=`);
    expect(decodeURIComponent(window.location.href)).toContain('(Ref: WA-TEST12)');
  });
});

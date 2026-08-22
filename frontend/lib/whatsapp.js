// Buy-on-WhatsApp: every WhatsApp entry point (listing button, float icon)
// goes through here so the click is recorded server-side before the visitor
// leaves the site. The backend stashes the Meta pixel cookies against a short
// reference code; the code rides along in the prefilled chat message, and if
// the chat turns into a sale the admin completes it by that code — which is
// what lets Meta attribute an off-site WhatsApp purchase back to the ad.

import { createWhatsAppCheckout } from '@/lib/api';
import { trackWhatsAppContact } from '@/lib/analytics';

export const WHATSAPP_NUMBER = '923712101998';

export function waLink(text = '') {
  const base = `https://wa.me/${WHATSAPP_NUMBER}`;
  return text ? `${base}?text=${encodeURIComponent(text)}` : base;
}

function prefilledMessage({ listing, quantity, ref }) {
  if (listing) {
    const qty = quantity > 1 ? ` x${quantity}` : '';
    const total = (Number(listing.price) * quantity).toLocaleString('en-PK');
    return `Hi! I want to buy: ${listing.title}${qty} — PKR ${total} (Ref: ${ref})`;
  }
  return `Hi GamesBazaar! (Ref: ${ref})`;
}

// Must be called synchronously from a click handler: popup blockers only
// allow window.open inside the user gesture, so the tab is opened first and
// pointed at the chat once the backend returns the reference code. If the
// API call fails the visitor still lands in WhatsApp — just untracked.
export function openWhatsAppChat({ listing = null, quantity = 1, page = '' } = {}) {
  const win = window.open('about:blank', '_blank');
  if (win) win.opener = null;
  const navigate = (url) => {
    if (win && !win.closed) win.location.href = url;
    else window.location.href = url; // popup blocked — reuse this tab
  };

  const body = { page: page || window.location.pathname };
  if (listing) {
    body.listing_id = listing.id;
    body.quantity = quantity;
  }

  return createWhatsAppCheckout(body)
    .then(({ ref }) => {
      trackWhatsAppContact(ref, listing, quantity);
      navigate(waLink(prefilledMessage({ listing, quantity, ref })));
    })
    .catch(() => {
      navigate(waLink(listing ? `Hi! I want to buy: ${listing.title}` : ''));
    });
}

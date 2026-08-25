// GA4 (gtag) and Meta Pixel (fbq) conversion helpers. Every call is a no-op
// when the corresponding script isn't loaded (ID not configured, ad blocker,
// SSR), so callers never need to guard.

import { reportListingView } from '@/lib/api';

const CURRENCY = 'PKR';

function gtag(...args) {
  if (typeof window !== 'undefined' && typeof window.gtag === 'function') {
    window.gtag(...args);
  }
}

function fbq(...args) {
  if (typeof window !== 'undefined' && typeof window.fbq === 'function') {
    window.fbq(...args);
  }
}

function gaItem(listing, quantity) {
  return {
    item_id: String(listing.id),
    item_name: listing.title,
    item_category: listing.game_name,
    item_category2: listing.category_name,
    price: Number(listing.price),
    quantity,
  };
}

function pixelContents(listing) {
  return {
    content_ids: [String(listing.id)],
    content_type: 'product',
    content_name: listing.title,
    content_category: listing.game_name,
  };
}

export function trackViewListing(listing) {
  const value = Number(listing.price);
  gtag('event', 'view_item', { currency: CURRENCY, value, items: [gaItem(listing, 1)] });
  // window.fbq exists whenever the pixel is configured (the Analytics stub
  // installs it even when an ad blocker stops fbevents.js from loading) —
  // so gating on it skips unconfigured environments but still reports
  // ad-blocked views. The backend sends the same ViewContent via the
  // Conversions API with this exact eventID, so Meta deduplicates the pair.
  if (typeof window === 'undefined' || typeof window.fbq !== 'function') return;
  const eventID =
    `vc-${listing.id}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  window.fbq('track', 'ViewContent', { ...pixelContents(listing), currency: CURRENCY, value }, { eventID });
  reportListingView(listing.id, eventID);
}

export function trackBeginCheckout(listing, quantity) {
  const value = Number(listing.price) * quantity;
  gtag('event', 'begin_checkout', { currency: CURRENCY, value, items: [gaItem(listing, quantity)] });
  fbq('track', 'InitiateCheckout', {
    ...pixelContents(listing),
    currency: CURRENCY,
    value,
    num_items: quantity,
  });
}

export function trackPurchase(order, listing, quantity) {
  const value = Number(listing.price) * quantity;
  gtag('event', 'purchase', {
    transaction_id: order.order_number ? String(order.order_number) : String(order.id),
    currency: CURRENCY,
    value,
    items: [gaItem(listing, quantity)],
  });
  // The backend sends the same Purchase via the Conversions API with this
  // exact eventID (purchase-<order id>), so Meta deduplicates the pair.
  fbq('track', 'Purchase', {
    ...pixelContents(listing),
    currency: CURRENCY,
    value,
    num_items: quantity,
  }, { eventID: `purchase-${order.id}` });
}

export function trackWhatsAppContact(ref, listing = null, quantity = 1) {
  const value = listing ? Number(listing.price) * quantity : undefined;
  gtag('event', 'whatsapp_click', listing
    ? { currency: CURRENCY, value, items: [gaItem(listing, quantity)] }
    : {});
  // The backend sends the same Contact via the Conversions API with this
  // exact eventID (wa-click-<ref>), so Meta deduplicates the pair.
  fbq('track', 'Contact', listing
    ? { ...pixelContents(listing), currency: CURRENCY, value }
    : {}, { eventID: `wa-click-${ref}` });
}

export function trackSignUp(method) {
  gtag('event', 'sign_up', { method });
  // No fbq here: Meta CompleteRegistration is sent server-side only
  // (Conversions API), so signups blocked by ad blockers still count.
}

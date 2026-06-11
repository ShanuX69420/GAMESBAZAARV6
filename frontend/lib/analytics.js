// GA4 (gtag) and Meta Pixel (fbq) conversion helpers. Every call is a no-op
// when the corresponding script isn't loaded (ID not configured, ad blocker,
// SSR), so callers never need to guard.

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
  fbq('track', 'ViewContent', { ...pixelContents(listing), currency: CURRENCY, value });
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
  fbq('track', 'Purchase', {
    ...pixelContents(listing),
    currency: CURRENCY,
    value,
    num_items: quantity,
  });
}

export function trackSignUp(method) {
  gtag('event', 'sign_up', { method });
  fbq('track', 'CompleteRegistration', { content_name: method });
}

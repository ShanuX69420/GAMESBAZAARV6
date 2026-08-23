// Review dates render on the server (UTC) and again in the browser (PKT).
// Without a pinned zone, a review posted between midnight and 5am PKT lands on
// different calendar days in the two renders — React treats that as a
// hydration mismatch, throws the server HTML away, and the client re-render
// wipes <html data-theme>, flipping dark mode off. Pin the zone: every buyer
// is in Pakistan, so PKT is also simply the right date to show.
export function formatReviewDate(value) {
  if (!value) return '';
  return new Date(value).toLocaleDateString('en-PK', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Karachi',
  });
}

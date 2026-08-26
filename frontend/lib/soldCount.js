// Sold-count display. Social proof only counts when it exists — a listing
// with no sales shows nothing rather than "0 sold".
export function formatSoldCount(count) {
  const n = Math.floor(Number(count));
  if (!Number.isFinite(n) || n < 1) return null;
  return `${n.toLocaleString()} sold`;
}

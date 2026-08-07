// Compact PKR price for game-card meta lines ("Starting from PKR 1,250").
// Returns null when there is no usable price so callers can fall back.
export function formatStartingPrice(value) {
  const price = Number(value);
  if (!Number.isFinite(price) || price <= 0) return null;
  return `PKR ${price.toLocaleString('en-PK', { maximumFractionDigits: 2 })}`;
}

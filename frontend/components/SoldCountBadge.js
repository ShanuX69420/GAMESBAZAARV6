// "N sold" pill for listing cards. Renders nothing until a listing has at
// least one completed sale (on-site or WhatsApp) — see lib/soldCount.js.

import { formatSoldCount } from '@/lib/soldCount';

export default function SoldCountBadge({ count }) {
  const label = formatSoldCount(count);
  if (!label) return null;
  return <span className="sold-count-pill">{label}</span>;
}

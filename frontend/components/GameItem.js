import { GameIconFallback } from '@/lib/icons';
import { optimizedImageUrl } from '@/lib/imageUrl';
import { formatStartingPrice } from '@/lib/price';
import { gameTilePath } from '@/lib/marketplaceUrls';

// A plain <a>, not next/link: the grid around these tiles (components/ListNav.js)
// turns a tap into a client-side navigation for every row at once, so /games'
// 500+ tiles add no per-row component to hydrate (mobile INP, 2026-09-13).
// Prefetch was already off — each tile scrolled into view would otherwise
// have cost a server render (2026-09-06 slow-click diagnosis).
export default function GameItem({ game }) {
  return (
    <a href={gameTilePath(game)} className="game-item">
      <div className="game-icon">
        {game.icon_url ? (
          // A plain <img> at one fixed optimizer URL rather than next/image's
          // src + 1x/2x srcSet — see lib/imageUrl.js. /games lists 700+ rows,
          // where that was ~250 KB of the HTML.
          <img
            src={optimizedImageUrl(game.icon_url)}
            alt={game.name}
            width={40}
            height={40}
            loading="lazy"
            decoding="async"
          />
        ) : (
          <GameIconFallback size={24} />
        )}
      </div>
      <div className="game-info">
        <div className="game-name">{game.name}</div>
        <div className="game-meta">
          {game.listing_count > 0 && formatStartingPrice(game.min_price)
            ? `Starting from ${formatStartingPrice(game.min_price)}`
            : game.listing_count > 0
              ? `${game.listing_count} ${game.listing_count === 1 ? 'offer' : 'offers'}`
              : `${game.category_count} ${game.category_count === 1 ? 'category' : 'categories'}`}
        </div>
      </div>
      <div className="game-arrow">›</div>
    </a>
  );
}

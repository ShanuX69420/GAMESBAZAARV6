import Link from 'next/link';
import { GameIconFallback } from '@/lib/icons';
import { optimizedImageUrl } from '@/lib/imageUrl';
import { formatStartingPrice } from '@/lib/price';
import { gameTilePath } from '@/lib/marketplaceUrls';

export default function GameItem({ game }) {
  return (
    <Link href={gameTilePath(game)} prefetch={false} className="game-item">
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
    </Link>
  );
}

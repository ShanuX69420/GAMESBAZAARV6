import Link from 'next/link';
import { getGameIcon } from '@/lib/icons';

export default function GameItem({ game }) {
  return (
    <Link href={`/games/${game.slug}`} className="game-item">
      <div className="game-icon">
        {game.icon_url ? (
          <img src={game.icon_url} alt={game.name} />
        ) : (
          getGameIcon(game.slug)
        )}
      </div>
      <div className="game-info">
        <div className="game-name">{game.name}</div>
        <div className="game-meta">
          {game.category_count} {game.category_count === 1 ? 'category' : 'categories'}
        </div>
      </div>
      <div className="game-arrow">›</div>
    </Link>
  );
}

import Link from 'next/link';
import Image from 'next/image';
import { getGameIcon } from '@/lib/icons';

export default function PopularPanel({ section }) {
  return (
    <div className="popular-panel">
      <h3 className="popular-panel-title">{section.title}</h3>
      <ul className="popular-panel-list">
        {section.items.map((item) => (
          <li key={`${item.game_slug}-${item.category_slug}`}>
            <Link
              href={`/games/${item.game_slug}/${item.category_slug}`}
              className="popular-panel-item"
            >
              <span className="popular-panel-icon">
                {item.icon_url ? (
                  <Image
                    src={item.icon_url}
                    alt={item.game_name}
                    width={32}
                    height={32}
                    loading="lazy"
                  />
                ) : (
                  getGameIcon(item.game_slug)
                )}
              </span>
              <span className="popular-panel-name">{item.game_name}</span>
              {item.listing_count > 0 && (
                <span className="popular-panel-count">
                  {item.listing_count} {item.listing_count === 1 ? 'offer' : 'offers'}
                </span>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

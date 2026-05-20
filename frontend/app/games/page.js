import { fetchGames } from '@/lib/api';
import GameItem from '@/components/GameItem';
import JsonLd from '@/components/JsonLd';
import Link from 'next/link';
import { breadcrumbJsonLd, collectionPageJsonLd, createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'All Games',
    description: 'Browse all games available on GamesBazaar. Find accounts, items, top-ups, and services for your favorite games.',
    path: '/games',
  }),
};

export default async function AllGamesPage() {
  let games = [];
  try {
    games = await fetchGames();
  } catch (error) {
    console.error('Failed to fetch games:', error);
  }

  return (
    <div className="container">
      <JsonLd
        data={[
          breadcrumbJsonLd([
            { name: 'Home', path: '/' },
            { name: 'All Games', path: '/games' },
          ]),
          collectionPageJsonLd({
            name: 'All Games',
            description: metadata.description,
            path: '/games',
          }),
        ]}
      />
      <div className="page-header">
        <div className="breadcrumb">
          <Link href="/">Home</Link>
          <span className="breadcrumb-sep">›</span>
          <span>All Games</span>
        </div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>All Games</h1>
      </div>

      {games.length > 0 ? (
        <div className="games-grid">
          {[...games].sort((a, b) => a.name.localeCompare(b.name)).map((game) => (
            <GameItem key={game.id} game={game} />
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <div className="empty-state-icon">🎮</div>
          <p>No games available yet. Check back soon!</p>
        </div>
      )}
    </div>
  );
}

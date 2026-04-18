import { fetchGames } from '@/lib/api';
import GameItem from '@/components/GameItem';

export default async function HomePage() {
  let games = [];
  try {
    games = await fetchGames();
  } catch (error) {
    console.error('Failed to fetch games:', error);
  }

  return (
    <div className="container">
      {/* Hero Section */}
      <section className="hero">
        <div className="hero-badge">🇵🇰 Made for Pakistan</div>
        <h1>Buy &amp; Sell Game Items,<br />Accounts &amp; Services</h1>
        <p>
          Pakistan&apos;s trusted digital gaming marketplace.
          Trade safely with verified sellers.
        </p>
      </section>

      {/* Games Section */}
      <section className="section">
        <div className="section-header">
          <h2 className="section-title">Popular Games</h2>
        </div>

        {games.length > 0 ? (
          <div className="games-grid">
            {games.map((game) => (
              <GameItem key={game.id} game={game} />
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon">🎮</div>
            <p>No games available yet. Check back soon!</p>
          </div>
        )}
      </section>
    </div>
  );
}

import { fetchGames } from '@/lib/api';
import GameItem from '@/components/GameItem';
import HomeCTA from '@/components/HomeCTA';
import Link from 'next/link';

const HOMEPAGE_GAME_LIMIT = 18;

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
        <h1>Pakistan&apos;s Gaming<br />Marketplace</h1>
        <p>
          Buy &amp; sell game accounts, items, top-ups, and services.
          Safe payments, verified sellers, and fast delivery.
        </p>
      </section>

      {/* Trust Strip */}
      <section className="trust-strip">
        <div className="trust-item">
          <span className="trust-icon">🛡️</span>
          <div className="trust-text">
            <strong>Buyer Protection</strong>
            <span>Pay safely — seller gets paid only after you confirm</span>
          </div>
        </div>
        <div className="trust-item">
          <span className="trust-icon">⚡</span>
          <div className="trust-text">
            <strong>Instant Delivery</strong>
            <span>Auto-delivery on select items</span>
          </div>
        </div>
        <div className="trust-item">
          <span className="trust-icon">✅</span>
          <div className="trust-text">
            <strong>Verified Sellers</strong>
            <span>Reviewed &amp; rated by real buyers</span>
          </div>
        </div>
      </section>

      {/* Games Section */}
      <section className="section">
        <div className="section-header">
          <h2 className="section-title">Popular Games</h2>
          {games.length > HOMEPAGE_GAME_LIMIT && (
            <Link href="/games" className="section-link">View All Games →</Link>
          )}
        </div>

        {games.length > 0 ? (
          <div className="games-grid">
            {games.slice(0, HOMEPAGE_GAME_LIMIT).map((game) => (
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

      {/* How It Works */}
      <section className="section how-it-works">
        <div className="section-header">
          <h2 className="section-title">How It Works</h2>
        </div>
        <div className="steps-grid">
          <div className="step-card">
            <div className="step-number">1</div>
            <h3>Browse &amp; Choose</h3>
            <p>Find the game item, account, or service you need from our verified sellers.</p>
          </div>
          <div className="step-connector" aria-hidden="true">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M5 12h14m-6-6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </div>
          <div className="step-card">
            <div className="step-number">2</div>
            <h3>Pay Securely</h3>
            <p>Your payment is protected — the seller only receives it after you confirm delivery.</p>
          </div>
          <div className="step-connector" aria-hidden="true">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M5 12h14m-6-6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </div>
          <div className="step-card">
            <div className="step-number">3</div>
            <h3>Receive &amp; Confirm</h3>
            <p>Get your item delivered and confirm to release payment. It&apos;s that simple.</p>
          </div>
        </div>
      </section>

      {/* CTA Section — guests only */}
      <HomeCTA />
    </div>
  );
}

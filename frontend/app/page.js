import { fetchGames, fetchHomePopular } from '@/lib/api';
import GameItem from '@/components/GameItem';
import PopularPanel from '@/components/PopularPanel';
import HomeCTA from '@/components/HomeCTA';
import Link from 'next/link';

const HOMEPAGE_GAME_LIMIT = 18;

export default async function HomePage() {
  let games = [];
  let popularSections = [];
  const [gamesResult, popularResult] = await Promise.allSettled([
    fetchGames(),
    fetchHomePopular(),
  ]);
  if (gamesResult.status === 'fulfilled') {
    games = gamesResult.value;
  } else {
    console.error('Failed to fetch games:', gamesResult.reason);
  }
  if (popularResult.status === 'fulfilled') {
    popularSections = popularResult.value.sections || [];
  } else {
    console.error('Failed to fetch popular sections:', popularResult.reason);
  }

  // Fallback when the popular panels are unavailable: only showcase games
  // that actually have stock — a small grid of real offers looks alive, a
  // big grid of empty games looks dead. Until any game has stock, fall back
  // to the full catalog so the section never renders empty. Everything
  // stays reachable via /games and search.
  const stockedGames = games.filter((game) => (game.listing_count || 0) > 0);
  const popularGames = (stockedGames.length > 0 ? stockedGames : games)
    .slice(0, HOMEPAGE_GAME_LIMIT);

  return (
    <div className="container">
      {/* Hero Section */}
      <section className="hero">
        <div className="hero-badge">
          <span className="hero-badge-dot"></span>
          Now Live — Start Trading Today
        </div>
        <h1>
          Pakistan&apos;s First <span className="hero-accent">Gaming</span>
          <br />Marketplace
        </h1>
        <p>
          Buy &amp; sell game accounts, items, top-ups, and services.
          Safe payments, verified sellers, and fast delivery.
        </p>
        <div className="hero-actions">
          <Link href="/games" className="hero-btn-primary">
            Browse Games
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
          </Link>
          <Link href="/register" className="hero-btn-outline">
            Start Selling
          </Link>
        </div>
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

      {/* Popular Section */}
      <section className="section">
        <div className="section-header">
          <h2 className="section-title">Popular Right Now</h2>
          {games.length > 0 && (
            <Link href="/games" className="section-link">View All Games →</Link>
          )}
        </div>

        {popularSections.length > 0 ? (
          <div className="popular-grid">
            {popularSections.map((section) => (
              <PopularPanel key={section.slug} section={section} />
            ))}
          </div>
        ) : popularGames.length > 0 ? (
          <div className="games-grid">
            {popularGames.map((game) => (
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
        <div className="section-header-accent">
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

import { fetchGames, fetchHomePopular } from '@/lib/api';
import { SITE_NAME, createPublicMetadata } from '@/lib/seo';
import GameItem from '@/components/GameItem';
import PopularPanel from '@/components/PopularPanel';
import HomeCTA from '@/components/HomeCTA';
import Link from 'next/link';

const HOMEPAGE_GAME_LIMIT = 18;

const HOME_TITLE = 'Buy Game Keys, Accounts, Top-Ups & Gift Cards in Pakistan';

export const metadata = {
  ...createPublicMetadata({
    title: HOME_TITLE,
    description:
      'Steam keys, game accounts, top-ups and gift cards at PKR prices. Pay with JazzCash, Easypaisa or bank transfer — instant delivery and easy refunds.',
    path: '/',
  }),
  // The layout's title template never applies to the page of its own segment,
  // so the brand suffix has to be spelled out here.
  title: `${HOME_TITLE} | ${SITE_NAME}`,
};

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
          Now Live — Instant Digital Delivery
        </div>
        <h1>
          Pakistan&apos;s <span className="hero-accent">Gaming</span>
          <br />Store
        </h1>
        <p>
          Game keys, accounts, top-ups, and gift cards — priced in PKR
          with safe local payments and fast delivery.
        </p>
        <div className="hero-actions">
          <Link href="/games" className="hero-btn-primary">
            Browse Games
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
          </Link>
          <Link href="/top-ups" className="hero-btn-outline">
            Top Up a Game
          </Link>
        </div>
      </section>

      {/* Trust Strip */}
      <section className="trust-strip">
        <div className="trust-item">
          <span className="trust-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/></svg>
          </span>
          <div className="trust-text">
            <strong>Secure Checkout</strong>
            <span>Pay safely — problems fixed fast or refunded to your wallet</span>
          </div>
        </div>
        <div className="trust-item">
          <span className="trust-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/></svg>
          </span>
          <div className="trust-text">
            <strong>Instant Delivery</strong>
            <span>Auto-delivery on select items</span>
          </div>
        </div>
        <div className="trust-item">
          <span className="trust-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76"/><path d="m9 12 2 2 4-4"/></svg>
          </span>
          <div className="trust-text">
            <strong>Trusted by Gamers</strong>
            <span>Rated &amp; reviewed by real buyers</span>
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
            <p>Find the game key, account, or top-up you need — all at Pakistani prices.</p>
          </div>
          <div className="step-connector" aria-hidden="true">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M5 12h14m-6-6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </div>
          <div className="step-card">
            <div className="step-number">2</div>
            <h3>Pay Securely</h3>
            <p>Pay from your wallet or directly at checkout — safe, fast, and in PKR.</p>
          </div>
          <div className="step-connector" aria-hidden="true">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M5 12h14m-6-6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </div>
          <div className="step-card">
            <div className="step-number">3</div>
            <h3>Receive &amp; Play</h3>
            <p>Get your item delivered — instantly on most orders. It&apos;s that simple.</p>
          </div>
        </div>
      </section>

      {/* CTA Section — guests only */}
      <HomeCTA />
    </div>
  );
}

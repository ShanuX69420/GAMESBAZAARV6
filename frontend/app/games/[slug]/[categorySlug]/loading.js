'use client';

import { useEffect } from 'react';

// Instant loading state for /games/<game>/<category> (brand and region
// pages). Shown the moment a buyer clicks a game or a category tab, while the
// server renders the real page — before this, the old page sat frozen for the
// whole round trip (0.5–1 s cold, 2026-09-06 slow-click diagnosis). Mirrors
// the page's own chrome (breadcrumb, title, tab strip, filter row, section
// header, card grid) with the real class names, so the swap to live content
// barely moves anything. React skips the fallback entirely when the payload
// arrives fast, so warm pages never flash it.

const CARD_COUNT = 6;
const TAB_WIDTHS = [96, 112, 88];

// Back/forward navigations must keep the browser-restored scroll position;
// everything else should start at the top (see the effect below).
let lastHistoryNavigation = 0;
if (typeof window !== 'undefined') {
  window.addEventListener('popstate', () => {
    lastHistoryNavigation = Date.now();
  });
}

export default function Loading() {
  // The router scrolls to the top only when the real page commits. Until
  // then the viewport stays wherever the link was clicked, and because this
  // skeleton is shorter than the page it replaces, a link clicked below the
  // first screen would show the reviews strip and footer instead of the
  // skeleton (measured 2026-09-06). Scroll now, the way the commit will.
  useEffect(() => {
    if (Date.now() - lastHistoryNavigation < 1500) return;
    if (window.scrollY > 0) window.scrollTo(0, 0);
  }, []);

  return (
    <div className="container category-skeleton" role="status" aria-live="polite" aria-label="Loading listings">
      <div className="page-header" aria-hidden="true">
        <div className="breadcrumb">
          <span className="skeleton-line" style={{ width: 44 }} />
          <span className="breadcrumb-sep">›</span>
          <span className="skeleton-line" style={{ width: 120 }} />
        </div>
        <div className="game-header">
          <div className="game-header-info">
            <div className="skeleton-line skeleton-heading" />
          </div>
        </div>
      </div>

      <div className="category-tabs" aria-hidden="true">
        {TAB_WIDTHS.map((width) => (
          <div key={width} className="category-tab skeleton-tab">
            <span className="skeleton-line" style={{ width }} />
          </div>
        ))}
      </div>

      <div className="skeleton-filter-row" aria-hidden="true">
        <span className="skeleton-line" style={{ width: 150 }} />
        <span className="skeleton-line" style={{ width: 130 }} />
      </div>

      <section className="section" style={{ paddingTop: 0 }} aria-hidden="true">
        <div className="section-header">
          <span className="skeleton-line" style={{ width: 150 }} />
          <span className="skeleton-line" style={{ width: 110 }} />
        </div>
        <div className="listing-cards-grid">
          {Array.from({ length: CARD_COUNT }, (_, index) => (
            <div key={index} className="listing-card skeleton-card">
              <div className="listing-card-header">
                <span className="skeleton-line" style={{ width: '68%' }} />
                <span className="skeleton-line" style={{ width: 64 }} />
              </div>
              <span className="skeleton-line" style={{ width: '42%' }} />
              <div className="listing-card-footer">
                <span className="skeleton-line" style={{ width: 96 }} />
                <span className="skeleton-line skeleton-button" />
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

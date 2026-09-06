'use client';

import { useEffect } from 'react';

// Loading state for /games/<game>/<category> (brand and region pages),
// mounted as loading.js in the (brand) and [regionSlug] segments — BELOW
// their layouts on purpose: a loading boundary above a layout lets its
// notFound() fire after the shell has gone out, and the not-found screen
// then ships with a 200 (the cached page would store it that way too).
// Shown while a clicked page's payload is on its way; since fix D that
// payload is a cached copy that arrives in one piece in ~0.2 s, so a warm
// click rarely sees it, and a first visit (cold cache) waits for the render
// the same way it did before. Mirrors the page's own chrome (breadcrumb,
// title, tab strip, filter row, section header, card grid) with the real
// class names, so the swap to live content barely moves anything.

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

export default function CategorySkeleton() {
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

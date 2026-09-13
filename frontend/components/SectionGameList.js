'use client';

import { Fragment, memo, startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE } from '@/lib/config';
import { GameIconFallback } from '@/lib/icons';
import { groupGamesByAlphabet } from '@/lib/gameGroups';
import { optimizedImageUrl } from '@/lib/imageUrl';
import { useListClickNavigation } from '@/lib/listNavigation';
import { formatStartingPrice } from '@/lib/price';
import { sectionParamsFromSearch, sectionUrl } from '@/lib/sectionLanding';
import SectionFilters from '@/components/SectionFilters';

const ALL_LETTERS = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')];

// One game row. Two things keep 400+ of these cheap on a phone (Search
// Console mobile INP > 200 ms, 2026-09-13):
// - memo: a dropdown tap only flips the list's busy flag, and without memo
//   that flip re-rendered every row inside the tap's own frame (200–300 ms at
//   4x CPU throttle);
// - a plain <a> instead of next/link: the grid's delegated click handler
//   (lib/listNavigation.js) does the client-side navigation, so hydration
//   has no per-row component to set up. Prefetch was already off here — every
//   row scrolled into view would otherwise cost a server render (2026-09-06).
const GameRow = memo(function GameRow({ item, linkSuffix }) {
  return (
    <a
      href={`/games/${item.game_slug}/${item.category_slug}${linkSuffix}`}
      className="game-item"
    >
      <div className="game-icon">
        {item.icon_url ? (
          // A plain <img> at one fixed optimizer URL — see lib/imageUrl.js.
          <img
            src={optimizedImageUrl(item.icon_url)}
            alt={item.game_name}
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
        <div className="game-name">{item.game_name}</div>
        <div className="game-meta">
          {item.listing_count > 0 && formatStartingPrice(item.min_price)
            ? `Starting from ${formatStartingPrice(item.min_price)}`
            : item.listing_count > 0
              ? `${item.listing_count} ${item.listing_count === 1 ? 'offer' : 'offers'}`
              : 'No offers yet'}
        </div>
      </div>
      <div className="game-arrow">›</div>
    </a>
  );
});

const rowKey = (item) => `${item.game_slug}-${item.category_slug}`;

// One letter of the A–Z list. Memoised so the busy flip above does not
// re-render its rows either.
const LetterGroup = memo(function LetterGroup({ letter, games, linkSuffix }) {
  return (
    <>
      <div
        className="alpha-divider"
        id={`section-${letter === '#' ? 'other' : letter}`}
      >
        <span className="alpha-divider-letter">{letter}</span>
      </div>
      {games.map((item) => (
        <GameRow key={rowKey(item)} item={item} linkSuffix={linkSuffix} />
      ))}
    </>
  );
});

// The filtered game list of a section page, and the dropdowns that drive it.
//
// It lives on the client for two reasons. The page above it is a cached copy of
// its bare URL, so ?method=/?region=/?sort= can only be applied after mount;
// and handing one client component the raw payload keeps the RSC flight data
// down to that JSON instead of 400 rows of serialised element tree (that tree
// was 360 KB of the 716 KB /keys used to ship). The rows still render on the
// server into the HTML, so the links are there for crawlers with no JS.
export default function SectionGameList({ slug, basePath, initialData }) {
  const [data, setData] = useState(initialData);
  const [busy, setBusy] = useState(false);
  // Only the newest request may write to state: dropdowns are quick to click
  // and a slow earlier answer must not overwrite a fast later one.
  const requestRef = useRef(0);
  const onRowClick = useListClickNavigation();

  const load = useCallback(async (selection) => {
    const ticket = requestRef.current + 1;
    requestRef.current = ticket;
    setBusy(true);
    try {
      const params = new URLSearchParams();
      if (selection.method) params.set('method', selection.method);
      if (selection.region) params.set('region', selection.region);
      if (selection.sort) params.set('sort', selection.sort);
      const query = params.toString();
      const res = await fetch(
        `${API_BASE}/api/categories/${encodeURIComponent(slug)}/games/${query ? `?${query}` : ''}`,
      );
      if (!res.ok) throw new Error('Failed to fetch section games');
      const fresh = await res.json();
      if (requestRef.current !== ticket) return;
      // Swapping 400+ rows is the one expensive render here. As a transition
      // React renders it in slices and lets a tap that lands meanwhile go
      // first instead of queueing behind the whole list.
      startTransition(() => {
        setData(fresh);
        setBusy(false);
      });
    } catch (error) {
      // Leave the list that is already on screen: a filter that fails to load
      // should not blank the page.
      console.error(`Failed to filter ${slug} games:`, error);
      if (requestRef.current === ticket) setBusy(false);
    }
  }, [slug]);

  // The server payload is always the bare section (the page is cached per URL
  // and never sees the query string). A shared or ad-landing link carrying
  // ?method=/?region=/?sort= is applied here with one more fetch — the same
  // in-place refresh a dropdown makes. This also re-runs on Back/Forward,
  // which moves the URL under us without remounting.
  useEffect(() => {
    const apply = () => {
      const landing = sectionParamsFromSearch(window.location.search);
      if (!landing) {
        requestRef.current += 1;
        setData(initialData);
        setBusy(false);
        return;
      }
      load(landing);
    };
    apply();
    window.addEventListener('popstate', apply);
    return () => window.removeEventListener('popstate', apply);
  }, [initialData, load]);

  const onFilterChange = (selection) => {
    load(selection);
    // pushState rather than router.push: the page is a cached copy that is
    // identical for every query, so a navigation would only re-fetch what is
    // already here. Next syncs its router with the native history methods.
    window.history.pushState(null, '', sectionUrl(basePath, selection));
  };

  const items = data?.items || [];
  const activeMethod = data?.method || '';
  const activeRegion = data?.region || '';
  const activeSort = data?.sort || '';

  // Carry the section's selections onto the game links so an ad landing on
  // /keys?method=…&region=… clicks through to a game page pre-filtered the
  // same way (the game page maps them onto its own filters).
  const linkParams = new URLSearchParams();
  if (activeMethod) linkParams.set('method', activeMethod);
  if (activeRegion) linkParams.set('region', activeRegion);
  const linkSuffix = linkParams.toString() ? `?${linkParams.toString()}` : '';

  // A-Z letter groups only make sense in the default (name) order; any other
  // sort would scatter the chosen order across the dividers. Memoised so the
  // groups (and the row objects inside them) keep their identity between
  // renders that did not change the data — that is what lets GameRow and
  // LetterGroup skip.
  const grouped = useMemo(
    () => (activeSort
      ? []
      : groupGamesByAlphabet(items.map((item) => ({ ...item, name: item.game_name })))),
    [items, activeSort],
  );
  const activeLetters = new Set(grouped.map((g) => g.letter));

  const methods = data?.methods || [];
  const regions = data?.regions || [];
  const sorts = data?.sorts || [];

  return (
    <>
      {(methods.length > 0 || regions.length > 0 || sorts.length > 0) && (
        <SectionFilters
          methods={methods}
          regions={regions}
          sorts={sorts}
          method={activeMethod}
          region={activeRegion}
          sort={activeSort}
          onChange={onFilterChange}
        />
      )}

      <div className={busy ? 'section-list section-list-busy' : 'section-list'} aria-busy={busy}>
        {items.length > 0 ? (
          activeSort ? (
            /* Sorted: one flat list, letter dividers would break the order */
            <div className="games-grid" onClick={onRowClick}>
              {items.map((item) => (
                <GameRow key={rowKey(item)} item={item} linkSuffix={linkSuffix} />
              ))}
            </div>
          ) : (
            <>
              {/* Alphabet quick-jump nav */}
              <nav className="alpha-nav" aria-label="Jump to letter">
                {ALL_LETTERS.map((letter) => (
                  <a
                    key={letter}
                    href={activeLetters.has(letter) ? `#section-${letter === '#' ? 'other' : letter}` : undefined}
                    className={`alpha-nav-item ${activeLetters.has(letter) ? 'active' : 'disabled'}`}
                    aria-disabled={!activeLetters.has(letter)}
                  >
                    {letter}
                  </a>
                ))}
              </nav>

              {/* Single continuous list with inline letter dividers */}
              <div className="games-grid games-grid-alpha" onClick={onRowClick}>
                {grouped.map(({ letter, games: sectionGames }) => (
                  <Fragment key={letter}>
                    <LetterGroup
                      letter={letter}
                      games={sectionGames}
                      linkSuffix={linkSuffix}
                    />
                  </Fragment>
                ))}
              </div>
            </>
          )
        ) : (
          <div className="empty-state">
            <p>
              {activeMethod || activeRegion
                ? 'No games match these filters yet. Try a different selection.'
                : 'Nothing here yet. Check back soon!'}
            </p>
          </div>
        )}
      </div>
    </>
  );
}

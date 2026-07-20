import { Fragment } from 'react';
import { fetchGames } from '@/lib/api';
import GameItem from '@/components/GameItem';
import JsonLd from '@/components/JsonLd';
import Link from 'next/link';
import { breadcrumbJsonLd, collectionPageJsonLd, createPublicMetadata } from '@/lib/seo';
import { groupGamesByAlphabet } from '@/lib/gameGroups';

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

  const grouped = groupGamesByAlphabet(games);
  const allLetters = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')];
  const activeLetters = new Set(grouped.map((g) => g.letter));

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
        <>
          {/* Alphabet quick-jump nav */}
          <nav className="alpha-nav" aria-label="Jump to letter">
            {allLetters.map((letter) => (
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
          <div className="games-grid games-grid-alpha">
            {grouped.map(({ letter, games: sectionGames }) => (
              <Fragment key={letter}>
                <div
                  className="alpha-divider"
                  id={`section-${letter === '#' ? 'other' : letter}`}
                >
                  <span className="alpha-divider-letter">{letter}</span>
                </div>
                {sectionGames.map((game) => (
                  <GameItem key={game.id} game={game} />
                ))}
              </Fragment>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-state">
          <p>No games available yet. Check back soon!</p>
        </div>
      )}
    </div>
  );
}

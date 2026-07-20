import { Fragment } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { fetchCategorySectionGames } from '@/lib/api';
import { GameIconFallback } from '@/lib/icons';
import JsonLd from '@/components/JsonLd';
import { breadcrumbJsonLd, collectionPageJsonLd } from '@/lib/seo';
import { groupGamesByAlphabet } from '@/lib/gameGroups';

// Shared body for the four category View All pages (/accounts, /top-ups,
// /offline-activation, /gift-cards) — same layout as /games, but each game
// links straight to its page for this category.
export default async function CategorySectionPage({ section }) {
  let items = [];
  try {
    const data = await fetchCategorySectionGames(section.slug);
    items = data.items || [];
  } catch (error) {
    console.error(`Failed to fetch ${section.slug} games:`, error);
  }

  const grouped = groupGamesByAlphabet(
    items.map((item) => ({ ...item, name: item.game_name }))
  );
  const allLetters = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')];
  const activeLetters = new Set(grouped.map((g) => g.letter));

  return (
    <div className="container">
      <JsonLd
        data={[
          breadcrumbJsonLd([
            { name: 'Home', path: '/' },
            { name: section.name, path: `/${section.slug}` },
          ]),
          collectionPageJsonLd({
            name: section.heading,
            description: section.description,
            path: `/${section.slug}`,
          }),
        ]}
      />
      <div className="page-header">
        <div className="breadcrumb">
          <Link href="/">Home</Link>
          <span className="breadcrumb-sep">›</span>
          <span>{section.name}</span>
        </div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>{section.heading}</h1>
      </div>

      {items.length > 0 ? (
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
                {sectionGames.map((item) => (
                  <Link
                    key={`${item.game_slug}-${item.category_slug}`}
                    href={`/games/${item.game_slug}/${item.category_slug}`}
                    className="game-item"
                  >
                    <div className="game-icon">
                      {item.icon_url ? (
                        <Image
                          src={item.icon_url}
                          alt={item.game_name}
                          width={40}
                          height={40}
                          loading="lazy"
                        />
                      ) : (
                        <GameIconFallback size={24} />
                      )}
                    </div>
                    <div className="game-info">
                      <div className="game-name">{item.game_name}</div>
                      <div className="game-meta">
                        {item.listing_count > 0
                          ? `${item.listing_count} ${item.listing_count === 1 ? 'offer' : 'offers'}`
                          : 'No offers yet'}
                      </div>
                    </div>
                    <div className="game-arrow">›</div>
                  </Link>
                ))}
              </Fragment>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-state">
          <p>Nothing here yet. Check back soon!</p>
        </div>
      )}
    </div>
  );
}

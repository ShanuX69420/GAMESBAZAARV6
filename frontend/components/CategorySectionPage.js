import { Fragment } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { fetchCategorySectionGames } from '@/lib/api';
import { GameIconFallback } from '@/lib/icons';
import JsonLd from '@/components/JsonLd';
import SectionFilters from '@/components/SectionFilters';
import SeoTextBlocks, { SeoInline } from '@/components/SeoTextBlocks';
import { splitSeoBlocks, stripInlineLinks } from '@/lib/seoText';
import { breadcrumbJsonLd, collectionPageJsonLd, faqPageJsonLd } from '@/lib/seo';
import { groupGamesByAlphabet } from '@/lib/gameGroups';
import { formatStartingPrice } from '@/lib/price';

// Server-rendered SEO copy below the game list. Same conventions as the
// game-category pages (lib/seoText.js). The FAQ renders from section.faq so
// the visible answers and the FAQPage JSON-LD can never diverge.
function SectionSeoText({ section }) {
  const blocks = splitSeoBlocks(section.seoText);
  const faq = section.faq || [];
  if (!blocks.length && !faq.length) return null;

  return (
    <section className="category-seo-text">
      <SeoTextBlocks blocks={blocks} />
      {faq.length > 0 && (
        <>
          <h2>Frequently asked questions</h2>
          {faq.map((item) => (
            <Fragment key={item.q}>
              <h3>{item.q}</h3>
              <p><SeoInline text={item.a} /></p>
            </Fragment>
          ))}
        </>
      )}
    </section>
  );
}

// Shared body for the category View All pages (/keys, /accounts, /top-ups,
// /gift-cards, /rentals) — same layout as /games, but each game
// links straight to its page for this category. Sections whose listings carry
// Method/Region filters (keys) also get dropdowns driven by ?method=/?region=,
// plus ?sort= — the default sort keeps the A-Z letter groups, any other sort
// renders one flat list in the server's order.
export default async function CategorySectionPage({
  section, method = '', region = '', sort = '',
}) {
  let items = [];
  let methods = [];
  let regions = [];
  let sorts = [];
  let activeMethod = '';
  let activeRegion = '';
  let activeSort = '';
  try {
    const data = await fetchCategorySectionGames(section.slug, { method, region, sort });
    items = data.items || [];
    methods = data.methods || [];
    regions = data.regions || [];
    sorts = data.sorts || [];
    activeMethod = data.method || '';
    activeRegion = data.region || '';
    activeSort = data.sort || '';
  } catch (error) {
    console.error(`Failed to fetch ${section.slug} games:`, error);
  }

  // Carry the section's selections onto the game links so an ad landing on
  // /keys?method=…&region=… clicks through to a game page pre-filtered the
  // same way (the game page maps them onto its own filters).
  const linkParams = new URLSearchParams();
  if (activeMethod) linkParams.set('method', activeMethod);
  if (activeRegion) linkParams.set('region', activeRegion);
  const linkSuffix = linkParams.toString() ? `?${linkParams.toString()}` : '';

  // A-Z letter groups only make sense in the default (name) order; any other
  // sort would scatter the chosen order across the dividers.
  const grouped = activeSort
    ? []
    : groupGamesByAlphabet(items.map((item) => ({ ...item, name: item.game_name })));
  const allLetters = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')];
  const activeLetters = new Set(grouped.map((g) => g.letter));

  const gameRow = (item) => (
    <Link
      key={`${item.game_slug}-${item.category_slug}`}
      href={`/games/${item.game_slug}/${item.category_slug}${linkSuffix}`}
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
          {item.listing_count > 0 && formatStartingPrice(item.min_price)
            ? `Starting from ${formatStartingPrice(item.min_price)}`
            : item.listing_count > 0
              ? `${item.listing_count} ${item.listing_count === 1 ? 'offer' : 'offers'}`
              : 'No offers yet'}
        </div>
      </div>
      <div className="game-arrow">›</div>
    </Link>
  );

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
          // JSON-LD answers are plain text: link markup in an answer is
          // rendered on the page but stripped here.
          ...(section.faq?.length ? [faqPageJsonLd([{
            questions: section.faq.map((item) => ({ q: item.q, a: stripInlineLinks(item.a) })),
          }])] : []),
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

      {(methods.length > 0 || regions.length > 0 || sorts.length > 0) && (
        <SectionFilters
          basePath={`/${section.slug}`}
          methods={methods}
          regions={regions}
          sorts={sorts}
          method={activeMethod}
          region={activeRegion}
          sort={activeSort}
        />
      )}

      {items.length > 0 ? (
        activeSort ? (
          /* Sorted: one flat list, letter dividers would break the order */
          <div className="games-grid">
            {items.map((item) => gameRow(item))}
          </div>
        ) : (
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
                {sectionGames.map((item) => gameRow(item))}
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

      <SectionSeoText section={section} />
    </div>
  );
}

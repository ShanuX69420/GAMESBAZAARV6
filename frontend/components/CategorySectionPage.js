import { Fragment } from 'react';
import Link from 'next/link';
import { fetchCategorySectionGames } from '@/lib/api';
import JsonLd from '@/components/JsonLd';
import SectionGameList from '@/components/SectionGameList';
import SeoTextBlocks, { SeoInline } from '@/components/SeoTextBlocks';
import { splitSeoBlocks, stripInlineLinks } from '@/lib/seoText';
import { breadcrumbJsonLd, collectionPageJsonLd, faqPageJsonLd } from '@/lib/seo';

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

// Shared body for the category View All pages (/keys, /accounts, /subscriptions,
// /gift-cards, /rentals) — same layout as /games, but each game links straight
// to its page for this category.
//
// A cached page: nothing here reads the request — no searchParams, cookies or
// headers — so Next prerenders each section once and refreshes it in the
// background (the fetch's own revalidate, lib/api.js). Sections whose listings
// carry Method/Region filters (keys) are still filterable: ?method=/?region=/
// ?sort= are applied by SectionGameList after mount, which is also where the
// rows render so the RSC payload carries the API's JSON rather than 400 rows
// of element tree (2026-09-07 — /keys was the last uncached section page, and
// the heaviest at 716 KB).
export default async function CategorySectionPage({ section }) {
  let data = null;
  try {
    data = await fetchCategorySectionGames(section.slug);
  } catch (error) {
    console.error(`Failed to fetch ${section.slug} games:`, error);
  }

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

      <SectionGameList
        slug={section.slug}
        basePath={`/${section.slug}`}
        initialData={data}
      />

      <SectionSeoText section={section} />
    </div>
  );
}

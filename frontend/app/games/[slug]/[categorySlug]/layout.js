import { Fragment, createElement } from 'react';
import JsonLd from '@/components/JsonLd';
import {
  breadcrumbJsonLd,
  collectionPageJsonLd,
  createPublicMetadata,
} from '@/lib/seo';

function titleFromSlug(value, fallback) {
  const text = String(value || '')
    .replace(/[-_+]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!text) return fallback;

  return text.replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

export async function generateMetadata({ params }) {
  const { slug, categorySlug } = await params;
  const gameName = titleFromSlug(slug, 'Game');
  const categoryName = titleFromSlug(categorySlug, 'Listings');
  const title = `${gameName} ${categoryName} Listings`;
  const description = `Browse ${gameName} ${categoryName} listings on GamesBazaar. Compare prices from verified sellers with buyer protection.`;

  return createPublicMetadata({
    title,
    description,
    path: `/games/${encodeURIComponent(slug)}/${encodeURIComponent(categorySlug)}`,
    openGraph: {
      type: 'website',
    },
  });
}

export default async function GameCategoryLayout({ children, params }) {
  const { slug, categorySlug } = await params;
  const gameName = titleFromSlug(slug, 'Game');
  const categoryName = titleFromSlug(categorySlug, 'Listings');
  const title = `${gameName} ${categoryName} Listings`;
  const description = `Browse ${gameName} ${categoryName} listings on GamesBazaar. Compare prices from verified sellers with buyer protection.`;
  const path = `/games/${encodeURIComponent(slug)}/${encodeURIComponent(categorySlug)}`;

  return createElement(
    Fragment,
    null,
    createElement(JsonLd, {
      data: [
        breadcrumbJsonLd([
          { name: 'Home', path: '/' },
          { name: 'All Games', path: '/games' },
          { name: gameName, path: `/games/${encodeURIComponent(slug)}` },
          { name: categoryName, path },
        ]),
        collectionPageJsonLd({ name: title, description, path }),
      ],
    }),
    children,
  );
}

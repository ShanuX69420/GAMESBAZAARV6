import { Fragment, createElement } from 'react';
import JsonLd from '@/components/JsonLd';
import { absoluteUrl, breadcrumbJsonLd, createPublicMetadata } from '@/lib/seo';

function sellerNameFromParam(username) {
  return String(username || 'Seller').trim() || 'Seller';
}

export async function generateMetadata({ params }) {
  const { username } = await params;
  const sellerName = sellerNameFromParam(username);
  const title = `${sellerName} Seller Profile`;
  const description = `View ${sellerName}'s seller profile, active listings, reviews, and completed sales on GamesBazaar.`;

  return createPublicMetadata({
    title,
    description,
    path: `/seller/${encodeURIComponent(username)}`,
    openGraph: {
      type: 'profile',
    },
  });
}

export default async function SellerProfileLayout({ children, params }) {
  const { username } = await params;
  const sellerName = sellerNameFromParam(username);
  const path = `/seller/${encodeURIComponent(username)}`;

  return createElement(
    Fragment,
    null,
    createElement(JsonLd, {
      data: [
        breadcrumbJsonLd([
          { name: 'Home', path: '/' },
          { name: `${sellerName} Seller Profile`, path },
        ]),
        {
          '@context': 'https://schema.org',
          '@type': 'ProfilePage',
          name: `${sellerName} Seller Profile`,
          url: absoluteUrl(path),
        },
      ],
    }),
    children,
  );
}

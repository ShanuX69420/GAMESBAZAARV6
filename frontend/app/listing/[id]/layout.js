import { Fragment, createElement } from 'react';
import JsonLd from '@/components/JsonLd';
import { getListingDetail } from '@/lib/api';
import { listingLifecycle } from '@/lib/listingLifecycle';
import { cleanText, listingDisplayName, listingPageTitle, listingSchemaBreadcrumbs } from '@/lib/listingSeo';
import { breadcrumbJsonLd, createPublicMetadata, productJsonLd } from '@/lib/seo';

function formatPrice(value) {
  const price = Number(value);
  if (!Number.isFinite(price)) return '';

  return `PKR ${price.toLocaleString('en-PK', {
    minimumFractionDigits: price % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  })}`;
}

function truncateDescription(value) {
  const text = cleanText(value);
  if (text.length <= 155) return text;

  return `${text.slice(0, 152).trimEnd()}...`;
}

function platformFromFilters(filterDisplay) {
  if (!filterDisplay || typeof filterDisplay !== 'object') return '';

  const platformEntry = Object.entries(filterDisplay).find(([name]) => (
    String(name).trim().toLowerCase() === 'platform'
  ));

  return cleanText(platformEntry?.[1]);
}

export async function generateMetadata({ params }) {
  const { id } = await params;
  const listingId = String(id || '').trim();

  try {
    const listing = await getListingDetail(listingId);
    // Gone (redirecting) or never indexed: the page itself never renders, so
    // the metadata only has to be harmless.
    const { state } = listingLifecycle(listing);
    if (state !== 'active' && state !== 'paused') throw new Error('listing has no page');

    const listingTitle = listingDisplayName(listing) || (listingId ? `Listing ${listingId}` : 'Listing');
    const price = formatPrice(listing.price);
    const { title, absolute } = listingPageTitle({ name: listingTitle, price });
    const platform = platformFromFilters(listing.filter_display);
    const categoryParts = [listing.game_name, platform, listing.category_name]
      .map(cleanText)
      .filter(Boolean);
    const categoryText = categoryParts.length ? `${categoryParts.join(' ')} listing` : 'listing';
    const sellerText = cleanText(listing.seller_name) ? ` sold by ${cleanText(listing.seller_name)}` : '';
    // Out of stock keeps the same title (the page keeps its ranking) but the
    // description says so, and points at the options that are in stock.
    const description = truncateDescription(
      state === 'paused'
        ? `${listingTitle} is out of stock on GamesBazaar right now. See the other ${categoryText.replace(/ listing$/, '')} options in stock, with instant delivery and secure checkout.`
        : `Buy ${listingTitle}${price ? ` for ${price}` : ''} on GamesBazaar. ${categoryText}${sellerText} with instant delivery and secure checkout.`
    );
    const canonicalPath = listingId ? `/listing/${encodeURIComponent(listingId)}` : '/';

    const metadata = createPublicMetadata({
      title,
      description,
      path: canonicalPath,
      openGraph: {
        type: 'website',
      },
    });
    if (absolute) {
      // Skip the root layout's " | GamesBazaar" template when it would push
      // the title past what search results show.
      metadata.title = { absolute: title };
    }
    return metadata;
  } catch {
    const title = listingId ? `Listing ${listingId}` : 'Listing';
    const description = 'View this GamesBazaar listing with secure checkout and instant delivery.';
    const canonicalPath = listingId ? `/listing/${encodeURIComponent(listingId)}` : '/';

    return createPublicMetadata({
      title,
      description,
      path: canonicalPath,
      robots: {
        index: false,
        follow: false,
      },
      openGraph: {
        type: 'website',
      },
    });
  }
}

function availabilityFromStatus(status) {
  if (status === 'active') return 'InStock';
  if (status === 'sold') return 'SoldOut';
  return 'OutOfStock';
}

export default async function ListingLayout({ children, params }) {
  const { id } = await params;
  const listingId = String(id || '').trim();

  let listing;
  try {
    listing = await getListingDetail(listingId);
  } catch {
    return children;
  }

  // No Product schema for a page that redirects or 404s.
  const { state } = listingLifecycle(listing);
  if (state !== 'active' && state !== 'paused') return children;

  const price = Number(listing.price);
  if (!Number.isFinite(price)) return children;

  const categoryParts = [listing.game_name, listing.category_name]
    .map(cleanText)
    .filter(Boolean);

  const listingReviews = listing.listing_reviews;
  const reviewCount = Number(listingReviews?.count) || 0;
  const name = listingDisplayName(listing) || `Listing ${listingId}`;
  const path = `/listing/${encodeURIComponent(listingId)}`;

  // Home › "<Game> <Category>" › this listing (SEO fix #2). The game is
  // left out on purpose: its URL always redirects (see listingSchemaBreadcrumbs).
  // Skipped when a pre-fix cached payload has no slugs: a breadcrumb with
  // dead links is worse than none.
  const schemaCrumbs = listingSchemaBreadcrumbs(listing);
  const breadcrumb = schemaCrumbs
    ? breadcrumbJsonLd([...schemaCrumbs, { name, path }])
    : null;

  return createElement(
    Fragment,
    null,
    createElement(JsonLd, {
      data: [productJsonLd({
        name,
        description: cleanText(listing.description),
        path,
        sku: listingId,
        brand: cleanText(listing.game_name),
        category: categoryParts.join(' - '),
        price: price.toFixed(2),
        availability: availabilityFromStatus(listing.status),
        sellerName: cleanText(listing.seller_name),
        aggregateRating: reviewCount > 0
          ? { value: listingReviews.average, count: reviewCount }
          : null,
        reviews: (listingReviews?.recent || []).map((review) => ({
          rating: review.rating,
          author: cleanText(review.reviewer_name),
          body: cleanText(review.comment),
          date: String(review.created_at || '').slice(0, 10),
        })),
      }), breadcrumb],
    }),
    children,
  );
}

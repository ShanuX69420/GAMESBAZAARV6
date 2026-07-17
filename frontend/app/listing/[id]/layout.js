import { Fragment, createElement } from 'react';
import JsonLd from '@/components/JsonLd';
import { getListingDetail } from '@/lib/api';
import { createPublicMetadata, productJsonLd } from '@/lib/seo';

function formatPrice(value) {
  const price = Number(value);
  if (!Number.isFinite(price)) return '';

  return `PKR ${price.toLocaleString('en-PK', {
    minimumFractionDigits: price % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  })}`;
}

function cleanText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
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
    const listingTitle = cleanText(listing.title) || (listingId ? `Listing ${listingId}` : 'Listing');
    const price = formatPrice(listing.price);
    const title = price ? `${listingTitle} - ${price}` : listingTitle;
    const platform = platformFromFilters(listing.filter_display);
    const categoryParts = [listing.game_name, platform, listing.category_name]
      .map(cleanText)
      .filter(Boolean);
    const categoryText = categoryParts.length ? `${categoryParts.join(' ')} listing` : 'listing';
    const sellerText = cleanText(listing.seller_name) ? ` sold by ${cleanText(listing.seller_name)}` : '';
    const protectionText = listing.buyer_protection_enabled ? ' with buyer protection' : '';
    const description = truncateDescription(
      `Buy ${listingTitle}${price ? ` for ${price}` : ''} on GamesBazaar. ${categoryText}${sellerText}${protectionText} and secure checkout.`
    );
    const canonicalPath = listingId ? `/listing/${encodeURIComponent(listingId)}` : '/';

    return createPublicMetadata({
      title,
      description,
      path: canonicalPath,
      openGraph: {
        type: 'website',
      },
    });
  } catch {
    const title = listingId ? `Listing ${listingId}` : 'Listing';
    const description = 'View this GamesBazaar listing with secure checkout, buyer protection, and seller chat.';
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

  const price = Number(listing.price);
  if (!Number.isFinite(price)) return children;

  const categoryParts = [listing.game_name, listing.category_name]
    .map(cleanText)
    .filter(Boolean);

  const listingReviews = listing.listing_reviews;
  const reviewCount = Number(listingReviews?.count) || 0;

  return createElement(
    Fragment,
    null,
    createElement(JsonLd, {
      data: productJsonLd({
        name: cleanText(listing.title) || `Listing ${listingId}`,
        description: cleanText(listing.description),
        path: `/listing/${encodeURIComponent(listingId)}`,
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
      }),
    }),
    children,
  );
}

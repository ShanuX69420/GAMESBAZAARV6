import { getListingDetail } from '@/lib/api';

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

    return {
      title,
      description,
      alternates: {
        canonical: canonicalPath,
      },
      openGraph: {
        title,
        description,
        url: canonicalPath,
        type: 'website',
        siteName: 'GamesBazaar',
      },
      twitter: {
        card: 'summary',
        title,
        description,
      },
    };
  } catch {
    const title = listingId ? `Listing ${listingId}` : 'Listing';
    const description = 'View this GamesBazaar listing with secure checkout, buyer protection, and seller chat.';

    return {
      title,
      description,
      robots: {
        index: false,
        follow: false,
      },
      openGraph: {
        title,
        description,
        type: 'website',
        siteName: 'GamesBazaar',
      },
    };
  }
}

export default function ListingLayout({ children }) {
  return children;
}

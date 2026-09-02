import { notFound, permanentRedirect } from 'next/navigation';
import { getListingDetail } from '@/lib/api';
import { listingLifecycle } from '@/lib/listingLifecycle';
import ListingDetailClient from './ListingDetailClient';

export default async function ListingDetailPage({ params }) {
  const { id } = await params;

  let listing = null;
  try {
    listing = await getListingDetail(id);
  } catch {
    listing = null;
  }
  if (!listing) notFound();

  // The backend decides the URL's fate (see lib/listingLifecycle.js): a
  // listing that is gone for good — deleted, retired, or out of stock for
  // over a month — sends the visitor to its heir with a permanent redirect;
  // one nobody ever indexed is a plain 404; a paused one renders as out of
  // stock. Both throws must stay outside the try above.
  const { state, redirectTo } = listingLifecycle(listing);
  if (state === 'gone') permanentRedirect(redirectTo);
  if (state !== 'active' && state !== 'paused') notFound();

  return <ListingDetailClient initialListing={listing} />;
}

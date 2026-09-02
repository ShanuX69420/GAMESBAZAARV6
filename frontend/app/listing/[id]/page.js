import { notFound, permanentRedirect } from 'next/navigation';
import { getListingDetail } from '@/lib/api';
import { retiredListingRedirect } from '@/lib/retiredListings';
import ListingDetailClient from './ListingDetailClient';

export default async function ListingDetailPage({ params }) {
  const { id } = await params;

  // Listings deleted by the catalog retirements: redirect before fetching, so
  // a stale cached copy of the old listing can never resurrect the page.
  const retiredPath = retiredListingRedirect(id);
  if (retiredPath) permanentRedirect(retiredPath);

  let initialListing = null;

  try {
    initialListing = await getListingDetail(id);
  } catch {
    notFound();
  }

  return <ListingDetailClient initialListing={initialListing} />;
}

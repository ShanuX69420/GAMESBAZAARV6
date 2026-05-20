import { notFound } from 'next/navigation';
import { getListingDetail } from '@/lib/api';
import ListingDetailClient from './ListingDetailClient';

export default async function ListingDetailPage({ params }) {
  const { id } = await params;
  let initialListing = null;

  try {
    initialListing = await getListingDetail(id);
  } catch {
    notFound();
  }

  return <ListingDetailClient initialListing={initialListing} />;
}

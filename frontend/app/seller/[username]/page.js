import { notFound } from 'next/navigation';
import { getSellerProfile, getSellerReviews } from '@/lib/api';
import SellerProfileClient from './SellerProfileClient';

const REVIEW_PAGE_SIZE = 20;
const PUBLIC_SELLER_REVALIDATE_SECONDS = 120;

async function fetchInitialSellerData(username) {
  const options = { next: { revalidate: PUBLIC_SELLER_REVALIDATE_SECONDS } };
  const [profile, reviewsData] = await Promise.all([
    getSellerProfile(username, options),
    getSellerReviews(username, { limit: REVIEW_PAGE_SIZE }, options),
  ]);

  return {
    profile,
    reviews: reviewsData.reviews || [],
    reviewPagination: reviewsData.pagination || null,
  };
}

export default async function SellerProfilePage({ params }) {
  const { username } = await params;
  let initialData;

  try {
    initialData = await fetchInitialSellerData(username);
  } catch {
    notFound();
  }

  return (
    <SellerProfileClient
      initialProfile={initialData.profile}
      initialReviews={initialData.reviews}
      initialReviewPagination={initialData.reviewPagination}
    />
  );
}

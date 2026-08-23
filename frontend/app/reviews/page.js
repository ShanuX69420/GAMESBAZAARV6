import { getAllReviews } from '@/lib/api';
import ReviewsClient from './ReviewsClient';

const REVIEW_PAGE_SIZE = 20;
const REVIEWS_REVALIDATE_SECONDS = 120;

export const metadata = {
  title: 'Customer Reviews',
  description:
    'What buyers say after their GamesBazaar orders — every review, with photos, newest first.',
};

export default async function ReviewsPage() {
  let initialData = null;
  try {
    initialData = await getAllReviews(
      { limit: REVIEW_PAGE_SIZE },
      { next: { revalidate: REVIEWS_REVALIDATE_SECONDS } },
    );
  } catch {
    // The client falls back to fetching on its own.
  }

  return <ReviewsClient initialData={initialData} />;
}

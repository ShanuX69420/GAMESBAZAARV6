import Link from 'next/link';
import { fetchSiteReviews } from '@/lib/api';
import { marqueeDuration, repeatToFillLoop } from '@/lib/marquee';

// Fewer reviews than this and there is nothing worth putting on every page.
const MIN_REVIEWS_TO_SHOW = 3;

function renderStars(rating) {
  return '★'.repeat(Math.round(rating)) + '☆'.repeat(5 - Math.round(rating));
}

function ReviewCard({ review }) {
  return (
    <li className="site-review-card">
      <div className="site-review-stars" aria-label={`${review.rating} out of 5 stars`}>
        {renderStars(review.rating)}
      </div>
      <p className="site-review-comment">{review.comment}</p>
      <div className="site-review-meta">
        <span className="site-review-author">Verified buyer</span>
        {review.listing_title && (
          <>
            <span className="site-review-sep">·</span>
            <span className="site-review-item">{review.listing_title}</span>
          </>
        )}
      </div>
    </li>
  );
}

// Sitewide review marquee, rendered above the footer on every page. It is a
// server component with a cached fetch, so the cards are in the initial HTML —
// no client fetch on every page load and no layout shift when they arrive.
export default async function SiteReviews() {
  let reviews = [];
  let summary = null;
  try {
    const data = await fetchSiteReviews();
    reviews = data.reviews || [];
    summary = data.summary || null;
  } catch (e) {
    // The strip is decoration on every page — a review API blip must never
    // take the footer (or the page) down with it.
    console.error('Failed to fetch site reviews:', e);
    return null;
  }

  if (reviews.length < MIN_REVIEWS_TO_SHOW) return null;

  const cards = repeatToFillLoop(reviews);
  const duration = marqueeDuration(cards.length);

  return (
    <section className="site-reviews" aria-labelledby="site-reviews-title">
      <div className="container site-reviews-head">
        {/* These are buyer reviews of SELLERS on specific orders, not reviews
            of the site — the heading has to say so. Cards like "this guy is the
            GOAT" under a claim about GamesBazaar reads as fake. */}
        <h2 id="site-reviews-title" className="site-reviews-title">
          What buyers say about their orders
        </h2>
        {summary?.average != null && summary.count > 0 && (
          <p className="site-reviews-summary">
            <span className="site-reviews-summary-stars" aria-hidden="true">
              {renderStars(summary.average)}
            </span>
            <span>
              {summary.average.toFixed(1)} average from {summary.count}{' '}
              {summary.count === 1 ? 'review' : 'reviews'}
            </span>
          </p>
        )}
        <Link href="/reviews" className="site-reviews-all-link">
          View all reviews
        </Link>
      </div>

      <div className="site-reviews-viewport">
        <ul className="site-reviews-track" style={{ '--site-reviews-duration': duration }}>
          {cards.map((review, index) => (
            <ReviewCard key={`${index}-${review.id}`} review={review} />
          ))}
        </ul>
        {/* Second copy of the same cards: the track scrolls exactly one copy's
            width and snaps back, which reads as an endless loop. Hidden from
            assistive tech so the reviews are not announced twice. */}
        <ul
          className="site-reviews-track site-reviews-track-clone"
          style={{ '--site-reviews-duration': duration }}
          aria-hidden="true"
        >
          {cards.map((review, index) => (
            <ReviewCard key={`clone-${index}-${review.id}`} review={review} />
          ))}
        </ul>
      </div>
    </section>
  );
}

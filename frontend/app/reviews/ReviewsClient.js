'use client';

import { useState, useEffect } from 'react';
import { getAllReviews } from '@/lib/api';
import { formatReviewDate } from '@/lib/dates';
import ReviewPhotos from '@/components/ReviewPhotos';

const REVIEW_PAGE_SIZE = 20;

function renderStars(rating) {
  return '★'.repeat(Math.round(rating)) + '☆'.repeat(5 - Math.round(rating));
}

// The public /reviews page: the honest full list — every rating, on-site and
// WhatsApp sales alike — unlike the marquee strip's positive-only showcase.
export default function ReviewsClient({ initialData = null }) {
  const [summary, setSummary] = useState(initialData?.summary || null);
  const [reviews, setReviews] = useState(initialData?.reviews || []);
  const [pagination, setPagination] = useState(initialData?.pagination || null);
  const [loading, setLoading] = useState(!initialData);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (initialData) return;
    getAllReviews({ limit: REVIEW_PAGE_SIZE })
      .then((data) => {
        setSummary(data.summary || null);
        setReviews(data.reviews || []);
        setPagination(data.pagination || null);
      })
      .catch(() => setError('Could not load reviews. Please try again.'))
      .finally(() => setLoading(false));
  }, [initialData]);

  async function loadMore() {
    if (pagination?.next_offset === null || pagination?.next_offset === undefined || loadingMore) return;
    setLoadingMore(true);
    try {
      const data = await getAllReviews({
        limit: REVIEW_PAGE_SIZE,
        offset: pagination.next_offset,
      });
      setReviews((prev) => [...prev, ...(data.reviews || [])]);
      setPagination(data.pagination || null);
    } catch {
      // keep what we have
    } finally {
      setLoadingMore(false);
    }
  }

  if (loading) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading reviews...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container">
        <div className="empty-state"><p>{error}</p></div>
      </div>
    );
  }

  return (
    <div className="container reviews-page">
      <h1 className="reviews-page-title">Customer Reviews</h1>
      <p className="reviews-page-subtitle">
        Every review buyers have left on their orders — newest first.
      </p>

      {summary && summary.count > 0 && (
        <div className="sp-rating-dist">
          <div className="sp-rd-left">
            <div className="sp-rd-big">{summary.average}</div>
            <div className="sp-rd-stars">{renderStars(summary.average)}</div>
            <div className="sp-rd-total">
              {summary.count} {summary.count === 1 ? 'review' : 'reviews'}
            </div>
          </div>
          <div className="sp-rd-bars">
            {[5, 4, 3, 2, 1].map((star) => {
              const count = summary.rating_distribution?.[String(star)] || 0;
              const pct = summary.count > 0 ? (count / summary.count * 100) : 0;
              return (
                <div key={star} className="sp-rd-row">
                  <span className="sp-rd-label">{star}★</span>
                  <div className="sp-rd-track">
                    <div className="sp-rd-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="sp-rd-count">{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {reviews.length === 0 ? (
        <div className="empty-state">
          <p>No reviews yet.</p>
        </div>
      ) : (
        <div className="reviews-list">
          {reviews.map((review) => (
            <div key={review.id} className="review-card">
              <div className="review-card-header">
                <span className="review-card-user">Buyer</span>
                <span className="review-card-date">
                  {formatReviewDate(review.created_at)}
                  {review.updated_at && (
                    <span className="review-edited-badge"> (edited)</span>
                  )}
                </span>
              </div>
              <div className="review-card-stars">{renderStars(review.rating)}</div>
              {review.comment && (
                <div className="review-card-comment">{review.comment}</div>
              )}
              <ReviewPhotos images={review.images} />
              {review.listing_title && (
                <div className="review-card-listing">Purchased: {review.listing_title}</div>
              )}
              {review.seller_reply && (
                <div className="review-reply-block">
                  <div className="review-reply-header">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="9 17 4 12 9 7"/>
                      <path d="M20 18v-2a4 4 0 00-4-4H4"/>
                    </svg>
                    <span>Seller&apos;s Reply</span>
                    {review.seller_reply_at && (
                      <span className="review-reply-date">
                        {formatReviewDate(review.seller_reply_at)}
                      </span>
                    )}
                  </div>
                  <div className="review-reply-text">{review.seller_reply}</div>
                </div>
              )}
            </div>
          ))}
          {pagination?.next_offset !== null && pagination?.next_offset !== undefined && (
            <button
              type="button"
              className="btn btn-outline btn-full"
              onClick={loadMore}
              disabled={loadingMore}
            >
              {loadingMore ? 'Loading...' : 'Load More Reviews'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

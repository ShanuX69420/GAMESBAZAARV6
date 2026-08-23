'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { getWhatsAppReviewContext, submitWhatsAppReview } from '@/lib/api';
import ReviewPhotos from '@/components/ReviewPhotos';
import ReviewPhotoPicker from '@/components/ReviewPhotoPicker';

const MAX_REVIEW_PHOTOS = 3;
const MAX_REVIEW_PHOTO_BYTES = 5 * 1024 * 1024;

// The page behind the review link sent in WhatsApp after a sale. The token in
// the URL is the whole handshake — no account, no login.
export default function WhatsAppReviewPage() {
  const { token } = useParams();
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [context, setContext] = useState(null);
  const [review, setReview] = useState(null);

  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [comment, setComment] = useState('');
  const [photos, setPhotos] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!token) return;
    getWhatsAppReviewContext(token)
      .then((data) => {
        setContext(data);
        if (data.reviewed) setReview(data.review);
      })
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [token]);

  function handlePhotoSelect(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    if (!files.length) return;
    setError('');
    if (files.length > MAX_REVIEW_PHOTOS - photos.length) {
      setError(`You can attach up to ${MAX_REVIEW_PHOTOS} photos.`);
      return;
    }
    for (const file of files) {
      if (!file.type.startsWith('image/')) {
        setError('Only image files can be attached.');
        return;
      }
      if (file.size > MAX_REVIEW_PHOTO_BYTES) {
        setError('Each photo must be 5MB or smaller.');
        return;
      }
    }
    setPhotos((prev) => [
      ...prev,
      ...files.map((file) => ({ file, previewUrl: URL.createObjectURL(file) })),
    ]);
  }

  function removePhoto(index) {
    setPhotos((prev) => {
      URL.revokeObjectURL(prev[index].previewUrl);
      return prev.filter((_, i) => i !== index);
    });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (rating === 0 || submitting) return;
    setError('');
    setSubmitting(true);
    try {
      const data = await submitWhatsAppReview(token, rating, comment, photos.map((p) => p.file));
      photos.forEach((photo) => URL.revokeObjectURL(photo.previewUrl));
      setReview(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="container wa-review-page">
        <div className="empty-state">
          <p>This review link is not valid. If you think that&apos;s wrong, message us on WhatsApp.</p>
          <Link href="/" className="btn btn-primary" style={{ marginTop: '12px' }}>Back to GamesBazaar</Link>
        </div>
      </div>
    );
  }

  if (review) {
    return (
      <div className="container wa-review-page">
        <div className="wa-review-card">
          <h1 className="wa-review-title">Thank you for your review!</h1>
          <div className="review-display-card">
            <div className="review-card-stars">
              {'★'.repeat(review.rating)}{'☆'.repeat(5 - review.rating)}
            </div>
            {review.comment && (
              <div className="review-card-comment">{review.comment}</div>
            )}
            <ReviewPhotos images={review.images} />
            {context?.listing_title && (
              <div className="review-card-listing">Purchased: {context.listing_title}</div>
            )}
          </div>
          <Link href="/" className="btn btn-outline" style={{ marginTop: '16px' }}>
            Browse GamesBazaar
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="container wa-review-page">
      <div className="wa-review-card">
        <h1 className="wa-review-title">How was your purchase?</h1>
        {context?.listing_title && (
          <p className="wa-review-subtitle">{context.listing_title}</p>
        )}
        {error && <div className="alert alert-error">{error}</div>}
        <form onSubmit={handleSubmit} className="review-form">
          <div className="review-stars-input">
            {[1, 2, 3, 4, 5].map((star) => (
              <button
                key={star}
                type="button"
                className={`review-star-btn ${star <= (hover || rating) ? 'active' : ''}`}
                onClick={() => setRating(star)}
                onMouseEnter={() => setHover(star)}
                onMouseLeave={() => setHover(0)}
              >
                ★
              </button>
            ))}
            {rating > 0 && (
              <span className="review-rating-text">
                {rating === 1 ? 'Poor' : rating === 2 ? 'Fair' : rating === 3 ? 'Good' : rating === 4 ? 'Great' : 'Excellent'}
              </span>
            )}
          </div>
          <div className="form-group">
            <textarea
              className="form-textarea"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Tell others about your experience (optional)"
              rows={3}
              maxLength={2000}
            />
          </div>
          <ReviewPhotoPicker
            newPhotos={photos}
            onSelect={handlePhotoSelect}
            onRemoveNew={removePhoto}
            onRemoveExisting={() => {}}
            max={MAX_REVIEW_PHOTOS}
          />
          <button type="submit" className="btn btn-primary" disabled={rating === 0 || submitting}>
            {submitting ? 'Submitting...' : 'Submit Review'}
          </button>
        </form>
      </div>
    </div>
  );
}

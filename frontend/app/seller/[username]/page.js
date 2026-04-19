'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { getSellerProfile, getSellerReviews, formatLastActive } from '@/lib/api';

export default function SellerProfilePage() {
  const params = useParams();
  const { username } = params;
  const [profile, setProfile] = useState(null);
  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    loadData();
  }, [username]);

  async function loadData() {
    try {
      const [profileData, reviewsData] = await Promise.all([
        getSellerProfile(username),
        getSellerReviews(username),
      ]);
      setProfile(profileData);
      setReviews(reviewsData);
    } catch (err) {
      setError('Seller not found.');
    } finally {
      setLoading(false);
    }
  }

  function renderStars(rating) {
    return '★'.repeat(Math.round(rating)) + '☆'.repeat(5 - Math.round(rating));
  }

  if (loading) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading seller profile...</div>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="container">
        <div className="empty-state">
          <div className="empty-state-icon">🚫</div>
          <p>{error || 'Seller not found.'}</p>
          <Link href="/" className="btn btn-primary" style={{ marginTop: '12px' }}>Back to Home</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="container">
      {/* Profile Header */}
      <div className="seller-profile-header">
        <div className="seller-avatar">
          {profile.username.charAt(0).toUpperCase()}
        </div>
        <div className="seller-profile-info">
          <div className="seller-profile-name">{profile.username}</div>
          <div className="seller-profile-meta">
            <span>
              {profile.is_online ? (
                <span style={{ color: 'var(--green-600)' }}>● Online</span>
              ) : (
                formatLastActive(profile.last_active)
              )}
            </span>
            <span>📅 Joined {new Date(profile.member_since).toLocaleDateString('en-PK', { month: 'long', year: 'numeric' })}</span>
          </div>
          {profile.avg_rating && (
            <div className="seller-profile-rating" style={{ marginTop: '8px' }}>
              <span className="seller-rating-stars">{renderStars(profile.avg_rating)}</span>
              <span className="seller-rating-number">{profile.avg_rating}</span>
              <span className="seller-rating-count">({profile.review_count} review{profile.review_count !== 1 ? 's' : ''})</span>
            </div>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="dashboard-stats">
        <div className="stat-card">
          <div className="stat-icon">⭐</div>
          <div className="stat-info">
            <div className="stat-value">{profile.avg_rating || '—'}</div>
            <div className="stat-label">Average Rating</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon">✅</div>
          <div className="stat-info">
            <div className="stat-value">{profile.completed_sales}</div>
            <div className="stat-label">Completed Sales</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon">🛒</div>
          <div className="stat-info">
            <div className="stat-value">{profile.active_listings}</div>
            <div className="stat-label">Active Listings</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon">💬</div>
          <div className="stat-info">
            <div className="stat-value">{profile.review_count}</div>
            <div className="stat-label">Reviews</div>
          </div>
        </div>
      </div>

      {/* Reviews */}
      <section className="section" style={{ marginTop: '24px' }}>
        <h2 className="page-title" style={{ fontSize: '1.2rem', marginBottom: '16px' }}>
          Reviews ({reviews.length})
        </h2>
        {reviews.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">⭐</div>
            <p>No reviews yet.</p>
          </div>
        ) : (
          <div className="reviews-list">
            {reviews.map((review) => (
              <div key={review.id} className="review-card">
                <div className="review-card-header">
                  <span className="review-card-user">Buyer</span>
                  <span className="review-card-date">
                    {new Date(review.created_at).toLocaleDateString('en-PK', {
                      day: 'numeric', month: 'short', year: 'numeric',
                    })}
                  </span>
                </div>
                <div className="review-card-stars">{renderStars(review.rating)}</div>
                {review.comment && (
                  <div className="review-card-comment">{review.comment}</div>
                )}
                {review.listing_title && (
                  <div className="review-card-listing">
                    Purchased: {review.listing_title}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

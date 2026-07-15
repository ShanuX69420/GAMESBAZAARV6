'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { getSellerProfile, getSellerReviews, formatLastActive, isOnlineFromLastActive, startConversation, replyToReview } from '@/lib/api';
import { buildSellerListingsPath } from '@/lib/marketplaceUrls';
import { useAuth } from '@/lib/auth';
import ReportModal from '@/components/ReportModal';

const REVIEW_PAGE_SIZE = 20;
const PRESENCE_TICK_MS = 30000;

export default function SellerProfileClient({
  initialProfile = null,
  initialReviews = [],
  initialReviewPagination = null,
}) {
  const params = useParams();
  const router = useRouter();
  const { username } = params;
  const { user } = useAuth();
  const [profile, setProfile] = useState(initialProfile);
  const [reviews, setReviews] = useState(initialReviews);
  const [reviewPagination, setReviewPagination] = useState(initialReviewPagination);
  const [loading, setLoading] = useState(!initialProfile);
  const [loadingMoreReviews, setLoadingMoreReviews] = useState(false);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState('shop');
  const [startingChat, setStartingChat] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const [replyingTo, setReplyingTo] = useState(null);
  const [replyText, setReplyText] = useState('');
  const [replyLoading, setReplyLoading] = useState(false);
  const [replyError, setReplyError] = useState('');
  const [presenceNow, setPresenceNow] = useState(() => Date.now());

  useEffect(() => {
    if (initialProfile) {
      setProfile(initialProfile);
      setReviews(initialReviews);
      setReviewPagination(initialReviewPagination);
      setLoading(false);
      return;
    }
    loadData();
  }, [username, initialProfile, initialReviews, initialReviewPagination]);

  useEffect(() => {
    const interval = setInterval(() => setPresenceNow(Date.now()), PRESENCE_TICK_MS);
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') setPresenceNow(Date.now());
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  useEffect(() => {
    if (!username || loading) return;
    let inFlight = false;
    let cancelled = false;
    let controller = null;

    const pollProfile = async () => {
      if (document.visibilityState !== 'visible') return;
      if (inFlight) return;
      inFlight = true;
      controller = new AbortController();
      try {
        const profileData = await getSellerProfile(username, { signal: controller.signal });
        if (!cancelled) setProfile(profileData);
      } catch (err) {
        if (err?.name !== 'AbortError') {
          // Silently ignore background polling errors
        }
      } finally {
        inFlight = false;
        controller = null;
      }
    };

    // The server-rendered profile can be up to 2 minutes stale (revalidate
    // window), which is longer than the online window — refresh immediately.
    pollProfile();
    const pollInterval = setInterval(pollProfile, PRESENCE_TICK_MS);

    return () => {
      cancelled = true;
      if (controller) controller.abort();
      clearInterval(pollInterval);
    };
  }, [username, loading]);


  async function loadData() {
    setLoading(true);
    try {
      const [profileData, reviewsData] = await Promise.all([
        getSellerProfile(username),
        getSellerReviews(username, { limit: REVIEW_PAGE_SIZE }),
      ]);
      setProfile(profileData);
      setReviews(reviewsData.reviews || []);
      setReviewPagination(reviewsData.pagination || null);
    } catch (err) {
      setError('Seller not found.');
    } finally {
      setLoading(false);
    }
  }

  async function loadMoreReviews() {
    if (!reviewPagination?.next_offset || loadingMoreReviews) return;
    setLoadingMoreReviews(true);
    try {
      const data = await getSellerReviews(username, {
        limit: REVIEW_PAGE_SIZE,
        offset: reviewPagination.next_offset,
      });
      setReviews(prev => [...prev, ...(data.reviews || [])]);
      setReviewPagination(data.pagination || null);
    } catch {
      // silently fail
    } finally {
      setLoadingMoreReviews(false);
    }
  }

  function renderStars(rating) {
    return '★'.repeat(Math.round(rating)) + '☆'.repeat(5 - Math.round(rating));
  }

  async function handleStartChat() {
    setStartingChat(true);
    try {
      const data = await startConversation(profile.user_id);
      router.push(`/inbox?c=${data.conversation_id || data.id}`);
    } catch (err) {
      alert(err.message || 'Could not start chat. Please log in first.');
    } finally {
      setStartingChat(false);
    }
  }

  async function handleReply(reviewId) {
    if (!replyText.trim() || replyLoading) return;
    setReplyLoading(true);
    setReplyError('');
    try {
      const updatedReview = await replyToReview(reviewId, replyText.trim());
      setReviews(prev => prev.map(r => r.id === reviewId ? updatedReview : r));
      setReplyingTo(null);
      setReplyText('');
    } catch (err) {
      setReplyError(err.message);
    } finally {
      setReplyLoading(false);
    }
  }

  const isOwnProfile = user && user.username === username;
  const sellerIsOnline = isOnlineFromLastActive(profile?.last_active, presenceNow);

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
    <div className="sp-page container">
      {/* ── Profile Header Card ──────────────────────────────── */}
      <div className="sp-header">
        <div className="sp-header-left">
          <div className="sp-avatar">
            <img src={profile.avatar_url || '/avatar-default.svg'} alt={profile.username} />
            <span className={`sp-avatar-dot ${sellerIsOnline ? 'online' : ''}`} />
          </div>
          <div className="sp-header-info">
            <div className="sp-name-row">
              <h1 className="sp-username">{profile.username}</h1>
              <span className="sp-verified-badge" title="Verified Seller">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--green-500)"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
              </span>
            </div>
            <div className="sp-meta-row">
              {profile.positive_pct !== null && (
                <span className="sp-positive">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14z"/><path d="M7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3"/></svg>
                  {profile.positive_pct}%
                </span>
              )}
              {profile.avg_rating && (
                <span className="sp-rating-inline">
                  <span className="sp-stars">{renderStars(profile.avg_rating)}</span>
                  {profile.avg_rating}
                </span>
              )}
              <span className="sp-meta-sep">·</span>
              <span className="sp-review-count-inline">{profile.review_count} review{profile.review_count !== 1 ? 's' : ''}</span>
            </div>
            <div className="sp-status-row">
              {sellerIsOnline ? (
                <span className="sp-online-badge">● Online</span>
              ) : (
                <span className="sp-offline-text">{formatLastActive(profile.last_active)}</span>
              )}
            </div>
          </div>
        </div>
        <div className="sp-header-right">
          <button
            className="sp-msg-btn"
            onClick={handleStartChat}
            disabled={startingChat}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
            {startingChat ? 'Starting...' : 'Message'}
          </button>
          {user && user.username !== profile.username && (
            <button
              className="report-flag-btn"
              onClick={() => setShowReport(true)}
              title="Report this seller"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/>
                <line x1="4" y1="22" x2="4" y2="15"/>
              </svg>
              Report
            </button>
          )}
        </div>
      </div>

      {/* ── Stats Bar ────────────────────────────────────────── */}
      <div className="sp-stats-bar">
        <div className="sp-stat-item">
          <span className="sp-stat-num">{profile.completed_sales}</span>
          <span className="sp-stat-lbl">Sales</span>
        </div>
        <div className="sp-stat-item">
          <span className="sp-stat-num">{profile.active_listings}</span>
          <span className="sp-stat-lbl">Listings</span>
        </div>
        <div className="sp-stat-item">
          <span className="sp-stat-num">{profile.review_count}</span>
          <span className="sp-stat-lbl">Reviews</span>
        </div>
        <div className="sp-stat-item">
          <span className="sp-stat-num">{new Date(profile.member_since).toLocaleDateString('en-PK', { month: 'short', year: 'numeric' })}</span>
          <span className="sp-stat-lbl">Member Since</span>
        </div>
      </div>

      {/* ── Tabs ─────────────────────────────────────────────── */}
      <div className="sp-tabs">
        <button
          className={`sp-tab ${activeTab === 'shop' ? 'active' : ''}`}
          onClick={() => setActiveTab('shop')}
        >
          Shop
        </button>
        <button
          className={`sp-tab ${activeTab === 'reviews' ? 'active' : ''}`}
          onClick={() => setActiveTab('reviews')}
        >
          Reviews
        </button>
      </div>

      {/* ── SHOP TAB — Game Service Tiles ─────────────────── */}
      {activeTab === 'shop' && (
        <div className="sp-shop">
          {profile.games && profile.games.length > 0 ? (
            <div className="sp-games-grid">
              {profile.games.map((game) => (
                <Link
                  key={game.game_slug}
                  href={buildSellerListingsPath({
                    gameSlug: game.game_slug,
                    categorySlug: game.categories[0]?.slug || '',
                    seller: profile.username,
                  })}
                  className="sp-game-tile"
                >
                  <div className="sp-game-tile-header">
                    <h3 className="sp-game-tile-name">{game.game_name}</h3>
                    <span className="sp-game-tile-count">{game.total_offers} offer{game.total_offers !== 1 ? 's' : ''}</span>
                  </div>
                  <div className="sp-game-tile-cats">
                    {game.categories.map((cat) => (
                      <span key={cat.slug} className="sp-game-tile-cat">
                        {cat.icon && <span>{cat.icon}</span>}
                        {cat.name}
                        <span className="sp-cat-count">{cat.count}</span>
                      </span>
                    ))}
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">🛒</div>
              <p>No active listings yet.</p>
            </div>
          )}
        </div>
      )}

      {/* ── REVIEWS TAB ──────────────────────────────────── */}
      {activeTab === 'reviews' && (
        <div className="sp-reviews">
          {/* Rating Distribution */}
          {profile.rating_distribution && profile.review_count > 0 && (
            <div className="sp-rating-dist">
              <div className="sp-rd-left">
                <div className="sp-rd-big">{profile.avg_rating}</div>
                <div className="sp-rd-stars">{renderStars(profile.avg_rating)}</div>
                <div className="sp-rd-total">{profile.review_count} reviews</div>
              </div>
              <div className="sp-rd-bars">
                {[5, 4, 3, 2, 1].map((star) => {
                  const count = profile.rating_distribution[String(star)] || 0;
                  const pct = profile.review_count > 0 ? (count / profile.review_count * 100) : 0;
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

          {/* Reviews List */}
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
                      {review.updated_at && (
                        <span className="review-edited-badge"> (edited)</span>
                      )}
                    </span>
                  </div>
                  <div className="review-card-stars">{renderStars(review.rating)}</div>
                  {review.comment && (
                    <div className="review-card-comment">{review.comment}</div>
                  )}
                  {review.listing_title && (
                    <div className="review-card-listing">Purchased: {review.listing_title}</div>
                  )}

                  {/* Seller Reply */}
                  {review.seller_reply && (
                    <div className="review-reply-block">
                      <div className="review-reply-header">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="9 17 4 12 9 7"/>
                          <path d="M20 18v-2a4 4 0 00-4-4H4"/>
                        </svg>
                        <span>Seller's Reply</span>
                        {review.seller_reply_at && (
                          <span className="review-reply-date">
                            {new Date(review.seller_reply_at).toLocaleDateString('en-PK', { day: 'numeric', month: 'short', year: 'numeric' })}
                          </span>
                        )}
                      </div>
                      <div className="review-reply-text">{review.seller_reply}</div>
                    </div>
                  )}

                  {/* Reply button for seller (own profile, no reply yet) */}
                  {isOwnProfile && !review.seller_reply && (
                    <>
                      {replyingTo === review.id ? (
                        <div className="review-reply-form">
                          {replyError && <div className="review-reply-error">{replyError}</div>}
                          <textarea
                            className="form-textarea"
                            value={replyText}
                            onChange={(e) => setReplyText(e.target.value)}
                            placeholder="Write your reply..."
                            rows={3}
                            maxLength={2000}
                          />
                          <div className="review-reply-form-actions">
                            <button
                              className="btn btn-outline btn-sm"
                              onClick={() => { setReplyingTo(null); setReplyText(''); setReplyError(''); }}
                              disabled={replyLoading}
                            >
                              Cancel
                            </button>
                            <button
                              className="btn btn-primary btn-sm"
                              onClick={() => handleReply(review.id)}
                              disabled={!replyText.trim() || replyLoading}
                            >
                              {replyLoading ? 'Posting...' : 'Post Reply'}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button
                          className="review-reply-btn"
                          onClick={() => { setReplyingTo(review.id); setReplyText(''); setReplyError(''); }}
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="9 17 4 12 9 7"/>
                            <path d="M20 18v-2a4 4 0 00-4-4H4"/>
                          </svg>
                          Reply
                        </button>
                      )}
                    </>
                  )}
                </div>
              ))}
              {reviewPagination?.next_offset !== null && reviewPagination?.next_offset !== undefined && (
                <button
                  type="button"
                  className="btn btn-outline btn-full"
                  onClick={loadMoreReviews}
                  disabled={loadingMoreReviews}
                >
                  {loadingMoreReviews ? 'Loading...' : 'Load More Reviews'}
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Report Modal */}
      {profile && (
        <ReportModal
          isOpen={showReport}
          onClose={() => setShowReport(false)}
          targetType="user"
          userId={profile.user_id}
          targetName={profile.username}
        />
      )}
    </div>
  );
}

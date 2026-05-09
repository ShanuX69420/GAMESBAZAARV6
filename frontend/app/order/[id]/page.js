'use client';

import { useState, useEffect, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getOrderDetail, confirmOrder, disputeOrder, deliverOrder, refundOrder, createReview, updateReview, replyToReview } from '@/lib/api';
import { orderLabel } from '@/lib/orderNumbers';
import ChatBox from '@/components/ChatBox';

export default function OrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { id } = params;
  const { user, loading } = useAuth();
  const [order, setOrder] = useState(null);
  const [loadingOrder, setLoadingOrder] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [deliverModal, setDeliverModal] = useState(false);
  const [deliveryNote, setDeliveryNote] = useState('');
  const [disputeModal, setDisputeModal] = useState(false);
  const [disputeReason, setDisputeReason] = useState('');
  const [confirmModal, setConfirmModal] = useState(false);
  const [reviewRating, setReviewRating] = useState(0);
  const [reviewHover, setReviewHover] = useState(0);
  const [reviewComment, setReviewComment] = useState('');
  const [reviewSubmitted, setReviewSubmitted] = useState(false);
  const [editingReview, setEditingReview] = useState(false);
  const [sellerReplyText, setSellerReplyText] = useState('');
  const [replyingToReview, setReplyingToReview] = useState(false);
  const [replyLoading, setReplyLoading] = useState(false);
  const actionRef = useRef(false);

  useEffect(() => {
    if (!loading && !user) router.push('/login');
  }, [user, loading, router]);

  useEffect(() => {
    if (user) loadOrder();
  }, [user, id]);

  async function loadOrder() {
    try {
      const data = await getOrderDetail(id);
      setOrder(data);
    } catch (err) {
      setError('Order not found or access denied.');
    } finally {
      setLoadingOrder(false);
    }
  }

  async function doAction(action) {
    if (actionRef.current) return;
    actionRef.current = true;
    setActionLoading(true);
    setError('');
    setSuccess('');
    try {
      await action();
      await loadOrder();
    } catch (err) {
      setError(err.message);
      actionRef.current = false;
    } finally {
      setActionLoading(false);
      actionRef.current = false;
    }
  }

  function handleConfirm() {
    setConfirmModal(false);
    doAction(async () => {
      const confirmed = await confirmOrder(id);
      if (confirmed.seller_payout_status === 'held') {
        setSuccess('Order confirmed! Seller payout is held by buyer protection for 14 days.');
      } else {
        setSuccess('Order confirmed! Funds released to seller.');
      }
    });
  }

  function handleDeliver() {
    doAction(async () => {
      await deliverOrder(id, deliveryNote);
      setSuccess('Order marked as delivered!');
      setDeliverModal(false);
      setDeliveryNote('');
    });
  }

  function handleDispute() {
    if (!disputeReason.trim()) return;
    doAction(async () => {
      await disputeOrder(id, disputeReason);
      setSuccess('Dispute opened. Admin will review your case.');
      setDisputeModal(false);
      setDisputeReason('');
    });
  }

  function handleRefund() {
    if (!window.confirm('Are you sure you want to refund this order? The buyer will receive a full refund.')) return;
    doAction(async () => {
      await refundOrder(id);
      setSuccess('Order refunded. Buyer has been credited.');
    });
  }

  async function handleReview(e) {
    e.preventDefault();
    if (reviewRating === 0) return;
    setError('');
    setSuccess('');
    try {
      if (editingReview && order.review_data) {
        await updateReview(order.review_data.id, reviewRating, reviewComment);
        setSuccess('Review updated!');
      } else {
        await createReview(id, reviewRating, reviewComment);
        setSuccess('Review submitted! Thank you for your feedback.');
      }
      setReviewSubmitted(true);
      setEditingReview(false);
      await loadOrder();
    } catch (err) {
      setError(err.message);
    }
  }

  function startEditingReview() {
    if (order.review_data) {
      setReviewRating(order.review_data.rating);
      setReviewComment(order.review_data.comment || '');
      setEditingReview(true);
      setReviewSubmitted(false);
    }
  }

  function cancelEditingReview() {
    setEditingReview(false);
    setReviewRating(0);
    setReviewHover(0);
    setReviewComment('');
  }

  async function handleSellerReply() {
    if (!sellerReplyText.trim() || replyLoading) return;
    setReplyLoading(true);
    setError('');
    setSuccess('');
    try {
      await replyToReview(order.review_data.id, sellerReplyText.trim());
      setSuccess('Reply posted!');
      setReplyingToReview(false);
      setSellerReplyText('');
      await loadOrder();
    } catch (err) {
      setError(err.message);
    } finally {
      setReplyLoading(false);
    }
  }

  if (loading || loadingOrder) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading order...</div>
      </div>
    );
  }

  if (!order) {
    return (
      <div className="container">
        <div className="empty-state">
          <div className="empty-state-icon">🚫</div>
          <p>{error || 'Order not found.'}</p>
          <Link href="/orders" className="btn btn-primary" style={{ marginTop: '12px' }}>Back to Purchases</Link>
        </div>
      </div>
    );
  }

  const isBuyer = user && user.id === order.buyer_id;
  const isSeller = user && user.id === order.seller_id;
  const otherUser = isBuyer ? order.seller_name : order.buyer_name;
  const hasReview = order.has_review || reviewSubmitted;
  const reviewData = order.review_data;
  const showReviewForm = isBuyer && order.status === 'completed' && (!hasReview || editingReview);
  const canOpenDispute = isBuyer && order.can_dispute;
  const displayOrderNumber = orderLabel(order);

  function getStatusColor(status) {
    switch (status) {
      case 'pending': return '#F59E0B';
      case 'delivered': return '#3B82F6';
      case 'completed': return '#16A34A';
      case 'disputed': return '#DC2626';
      case 'cancelled': return '#6B7280';
      default: return '#6B7280';
    }
  }

  function getStatusIcon(status) {
    switch (status) {
      case 'pending': return '⏳';
      case 'delivered': return '📦';
      case 'completed': return '✅';
      case 'disputed': return '⚠️';
      case 'cancelled': return '❌';
      default: return '📋';
    }
  }

  function renderStars(rating) {
    return '★'.repeat(Math.round(rating)) + '☆'.repeat(5 - Math.round(rating));
  }

  return (
    <div className="container">
      {/* Breadcrumb */}
      <div className="page-header">
        <div className="breadcrumb">
          <Link href={isSeller ? '/sales' : '/orders'}>{isSeller ? 'Sales' : 'Purchases'}</Link>
          <span className="breadcrumb-sep">›</span>
          <span>Order {displayOrderNumber}</span>
        </div>
      </div>

      {success && <div className="alert alert-success">{success}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      <div className="order-detail-layout">
        {/* Left: Order Info */}
        <div className="order-detail-main">
          <div className="order-detail-header">
            <h1 className="order-detail-title">Order {displayOrderNumber}</h1>
            <span
              className="order-detail-status"
              style={{ background: getStatusColor(order.status) + '20', color: getStatusColor(order.status) }}
            >
              {getStatusIcon(order.status)} {order.status_display}
            </span>
          </div>

          {/* Auto-confirm banner for delivered orders (buyer view) */}
          {isBuyer && order.status === 'delivered' && (
            <div className="order-autoconfirm-banner">
              <div className="order-autoconfirm-content">
                <svg className="order-autoconfirm-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                  <polyline points="22 4 12 14.01 9 11.01"/>
                </svg>
                <div className="order-autoconfirm-text">
                  <strong>Awaiting your confirmation</strong>
                  <p>The seller has completed the delivery. If you received the wrong / incomplete / invalid items, please file a report or the order will auto-confirm after 3 days.</p>
                </div>
              </div>
              <button
                className="order-autoconfirm-btn"
                onClick={() => setConfirmModal(true)}
                disabled={actionLoading}
              >
                Order received
              </button>
            </div>
          )}

          {/* Order info grid */}
          <div className="order-info-grid">
            <div className="order-info-item">
              <span className="order-info-label">ITEM</span>
              <span className="order-info-value">
                {order.listing_id ? (
                  <Link href={`/listing/${order.listing_id}`} style={{ color: 'var(--green-600)' }}>
                    {order.listing_title}
                  </Link>
                ) : (
                  order.listing_title
                )}
              </span>
            </div>
            <div className="order-info-item">
              <span className="order-info-label">{isBuyer ? 'SELLER' : 'BUYER'}</span>
              <span className="order-info-value">
                {isBuyer ? (
                  <Link href={`/seller/${order.seller_name}`} style={{ color: 'var(--green-600)' }}>{otherUser}</Link>
                ) : (
                  otherUser
                )}
              </span>
            </div>
            <div className="order-info-item">
              <span className="order-info-label">QUANTITY</span>
              <span className="order-info-value">{order.quantity}</span>
            </div>
            <div className="order-info-item">
              <span className="order-info-label">UNIT PRICE</span>
              <span className="order-info-value">PKR {order.unit_price}</span>
            </div>
          </div>

          {/* Delivery note */}
          {order.delivery_note && (
            <div className="order-detail-section">
              <h3 className="order-detail-section-title">
                {order.is_auto_delivery ? (
                  <>
                    <svg className="instant-delivery-icon" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" style={{ marginRight: '6px', verticalAlign: '-3px' }}>
                      <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z"/>
                    </svg>
                    Auto-Delivered Content
                  </>
                ) : '📝 Delivery Details'}
              </h3>
              <div className={`order-delivery-note ${order.is_auto_delivery ? 'order-auto-delivery-note' : ''}`} style={{ margin: 0 }}>
                <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0 }}>
                  {order.delivery_note}
                </pre>
              </div>
            </div>
          )}

          {/* Delivery Instructions */}
          {order.delivery_instructions && (
            <div className="order-detail-section">
              <h3 className="order-detail-section-title">📋 Seller Instructions</h3>
              <div className="order-delivery-note" style={{ margin: 0, background: '#F0F9FF', borderColor: '#BAE6FD', color: '#0C4A6E' }}>
                <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0 }}>
                  {order.delivery_instructions}
                </pre>
              </div>
            </div>
          )}

          {/* Dispute reason */}
          {order.dispute_reason && (
            <div className="order-detail-section">
              <h3 className="order-detail-section-title">⚠️ Dispute Reason</h3>
              <div className="order-dispute-note" style={{ margin: 0 }}>
                {order.dispute_reason}
              </div>
            </div>
          )}

          {/* Order footer info */}
          <div className="order-detail-footer">
            <div className="order-detail-date">
              <span className="order-info-label">OPENED</span>
              <span>{new Date(order.created_at).toLocaleString('en-PK', {
                day: 'numeric', month: 'long', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
              })}</span>
            </div>
            <div className="order-detail-total">
              <span className="order-info-label">TOTAL</span>
              <span className="order-total-amount">PKR {Number(order.total_amount).toLocaleString('en-PK', { minimumFractionDigits: 2 })}</span>
            </div>
          </div>

          {isSeller && (
            <div className="order-detail-footer" style={{ borderTop: 'none', paddingTop: 0, marginTop: '-8px' }}>
              <div></div>
              <div className="order-detail-total">
                <span className="order-info-label">YOU RECEIVE</span>
                <span style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--green-600)' }}>
                  PKR {Number(order.seller_amount).toLocaleString('en-PK', { minimumFractionDigits: 2 })}
                </span>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="order-detail-actions">
            <h3 className="order-detail-section-title">Actions</h3>
            <div className="order-action-buttons">
              {/* Buyer actions */}
              {canOpenDispute && (
                <>
                  <button
                    className="btn btn-outline"
                    onClick={() => { setDisputeModal(true); setDisputeReason(''); }}
                    disabled={actionLoading}
                  >
                    ⚠️ Open Dispute
                  </button>
                </>
              )}

              {/* Seller actions */}
              {isSeller && order.status === 'pending' && (
                <button
                  className="btn btn-primary"
                  onClick={() => { setDeliverModal(true); setDeliveryNote(''); }}
                  disabled={actionLoading}
                >
                  📦 Deliver Order
                </button>
              )}
              {isSeller && order.status !== 'cancelled' && (
                <button
                  className="btn btn-outline btn-danger"
                  onClick={handleRefund}
                  disabled={actionLoading}
                >
                  {actionLoading ? 'Processing...' : '💸 Refund Buyer'}
                </button>
              )}

              {/* Completed/cancelled messaging */}
              {order.status === 'completed' && isSeller && order.seller_payout_status === 'held' && (
                <div className="order-completed-msg" style={{ padding: '12px 0' }}>
                  Payout is held by buyer protection until {new Date(order.seller_payout_available_at).toLocaleString('en-PK', {
                    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
                  })}.
                </div>
              )}
              {order.status === 'completed' && !(isSeller && order.seller_payout_status === 'held') && (
                <div className="order-completed-msg" style={{ padding: '12px 0' }}>
                  ✅ This order has been completed. {isSeller ? 'Funds have been credited to your wallet.' : 'Thank you for your purchase!'}
                </div>
              )}
              {order.status === 'completed' && canOpenDispute && (
                <div className="order-completed-msg" style={{ padding: '0 0 12px', color: 'var(--text-tertiary)' }}>
                  Buyer protection is still active, so you can open a dispute if something is wrong.
                </div>
              )}
              {order.status === 'cancelled' && (
                <div style={{ color: 'var(--text-tertiary)', padding: '12px 0' }}>
                  ❌ This order has been cancelled and the buyer was refunded.
                </div>
              )}
            </div>
          </div>

          {/* Review Section — Buyer can create or edit review */}
          {showReviewForm && (
            <div className="order-detail-actions">
              <h3 className="order-detail-section-title">
                {editingReview ? '✏️ Edit Your Review' : '⭐ Leave a Review'}
              </h3>
              <form onSubmit={handleReview} className="review-form">
                <div className="review-stars-input">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <button
                      key={star}
                      type="button"
                      className={`review-star-btn ${star <= (reviewHover || reviewRating) ? 'active' : ''}`}
                      onClick={() => setReviewRating(star)}
                      onMouseEnter={() => setReviewHover(star)}
                      onMouseLeave={() => setReviewHover(0)}
                    >
                      ★
                    </button>
                  ))}
                  {reviewRating > 0 && (
                    <span className="review-rating-text">
                      {reviewRating === 1 ? 'Poor' : reviewRating === 2 ? 'Fair' : reviewRating === 3 ? 'Good' : reviewRating === 4 ? 'Great' : 'Excellent'}
                    </span>
                  )}
                </div>
                <div className="form-group">
                  <textarea
                    className="form-textarea"
                    value={reviewComment}
                    onChange={(e) => setReviewComment(e.target.value)}
                    placeholder="Tell others about your experience (optional)"
                    rows={3}
                  />
                </div>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <button type="submit" className="btn btn-primary" disabled={reviewRating === 0}>
                    {editingReview ? 'Update Review' : 'Submit Review'}
                  </button>
                  {editingReview && (
                    <button type="button" className="btn btn-outline" onClick={cancelEditingReview}>
                      Cancel
                    </button>
                  )}
                </div>
              </form>
            </div>
          )}

          {/* Show existing review (buyer view) */}
          {isBuyer && hasReview && !editingReview && reviewData && (
            <div className="order-detail-actions">
              <div className="review-display-card">
                <div className="review-display-header">
                  <div>
                    <div className="review-card-stars">{renderStars(reviewData.rating)}</div>
                    <span className="review-display-label">Your review</span>
                  </div>
                  <button className="review-edit-btn" onClick={startEditingReview} title="Edit review">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
                      <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                    Edit
                  </button>
                </div>
                {reviewData.comment && (
                  <div className="review-card-comment">{reviewData.comment}</div>
                )}
                {/* Show seller reply */}
                {reviewData.seller_reply && (
                  <div className="review-reply-block">
                    <div className="review-reply-header">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="9 17 4 12 9 7"/>
                        <path d="M20 18v-2a4 4 0 00-4-4H4"/>
                      </svg>
                      <span>Seller's Reply</span>
                      {reviewData.seller_reply_at && (
                        <span className="review-reply-date">
                          {new Date(reviewData.seller_reply_at).toLocaleDateString('en-PK', { day: 'numeric', month: 'short', year: 'numeric' })}
                        </span>
                      )}
                    </div>
                    <div className="review-reply-text">{reviewData.seller_reply}</div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Seller view of the review on this order */}
          {isSeller && hasReview && reviewData && (
            <div className="order-detail-actions">
              <h3 className="order-detail-section-title">⭐ Buyer's Review</h3>
              <div className="review-display-card">
                <div className="review-card-stars">{renderStars(reviewData.rating)}</div>
                {reviewData.comment && (
                  <div className="review-card-comment">{reviewData.comment}</div>
                )}
                {reviewData.seller_reply ? (
                  <div className="review-reply-block">
                    <div className="review-reply-header">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="9 17 4 12 9 7"/>
                        <path d="M20 18v-2a4 4 0 00-4-4H4"/>
                      </svg>
                      <span>Your Reply</span>
                    </div>
                    <div className="review-reply-text">{reviewData.seller_reply}</div>
                  </div>
                ) : replyingToReview ? (
                  <div className="review-reply-form">
                    <textarea
                      className="form-textarea"
                      value={sellerReplyText}
                      onChange={(e) => setSellerReplyText(e.target.value)}
                      placeholder="Write your reply to this review..."
                      rows={3}
                      maxLength={2000}
                    />
                    <div className="review-reply-form-actions">
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => { setReplyingToReview(false); setSellerReplyText(''); }}
                        disabled={replyLoading}
                      >
                        Cancel
                      </button>
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={handleSellerReply}
                        disabled={!sellerReplyText.trim() || replyLoading}
                      >
                        {replyLoading ? 'Posting...' : 'Post Reply'}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    className="review-reply-btn"
                    onClick={() => setReplyingToReview(true)}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="9 17 4 12 9 7"/>
                      <path d="M20 18v-2a4 4 0 00-4-4H4"/>
                    </svg>
                    Reply to Review
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Right: Chat */}
        <div className="order-detail-chat">
          {order.conversation_id ? (
            <ChatBox conversationId={order.conversation_id} otherUserName={otherUser} />
          ) : (
            <div className="order-chat-placeholder">
              <div className="empty-state-icon">💬</div>
              <p>Chat will be available once a conversation is started.</p>
            </div>
          )}
        </div>
      </div>

      {/* Deliver Modal */}
      {deliverModal && (
        <div className="image-preview-overlay" onClick={() => setDeliverModal(false)}>
          <div className="image-preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="image-preview-header">
              <span>Deliver Order {displayOrderNumber}</span>
              <button className="image-preview-close" onClick={() => setDeliverModal(false)}>✕</button>
            </div>
            <div style={{ padding: '20px' }}>
              <div className="form-group">
                <label className="form-label">Delivery Details</label>
                <textarea
                  className="form-textarea"
                  value={deliveryNote}
                  onChange={(e) => setDeliveryNote(e.target.value)}
                  placeholder="Account credentials, activation code, download link, etc..."
                  rows={5}
                />
              </div>
              <div style={{ display: 'flex', gap: '10px', marginTop: '16px', justifyContent: 'flex-end' }}>
                <button className="btn btn-outline" onClick={() => setDeliverModal(false)}>Cancel</button>
                <button className="btn btn-primary" onClick={handleDeliver} disabled={actionLoading}>
                  {actionLoading ? 'Delivering...' : '📦 Mark as Delivered'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Dispute Modal */}
      {disputeModal && (
        <div className="image-preview-overlay" onClick={() => setDisputeModal(false)}>
          <div className="image-preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="image-preview-header">
              <span>Open Dispute</span>
              <button className="image-preview-close" onClick={() => setDisputeModal(false)}>✕</button>
            </div>
            <div style={{ padding: '20px' }}>
              <div className="form-group">
                <label className="form-label">Reason for dispute *</label>
                <textarea
                  className="form-textarea"
                  value={disputeReason}
                  onChange={(e) => setDisputeReason(e.target.value)}
                  placeholder="Describe the issue..."
                  rows={4}
                  required
                />
              </div>
              <div style={{ display: 'flex', gap: '10px', marginTop: '16px', justifyContent: 'flex-end' }}>
                <button className="btn btn-outline" onClick={() => setDisputeModal(false)}>Cancel</button>
                <button
                  className="btn btn-primary"
                  onClick={handleDispute}
                  disabled={!disputeReason.trim() || actionLoading}
                >
                  {actionLoading ? 'Submitting...' : 'Submit Dispute'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Received Modal */}
      {confirmModal && (
        <div className="confirm-order-overlay" onClick={() => !actionLoading && setConfirmModal(false)}>
          <div className="confirm-order-modal" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-order-header">
              <div className="confirm-order-header-left">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                  <polyline points="22 4 12 14.01 9 11.01"/>
                </svg>
                <h3>Confirm Order Received</h3>
              </div>
              <button className="confirm-order-close" onClick={() => !actionLoading && setConfirmModal(false)}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>

            <div className="confirm-order-body">
              {/* Item info */}
              <div className="confirm-order-item">
                <div className="confirm-order-item-name">{order.listing_title}</div>
                <div className="confirm-order-item-meta">
                  Order {displayOrderNumber} &middot; from {order.seller_name}
                </div>
              </div>

              {/* Order summary */}
              <div className="confirm-order-summary">
                <div className="confirm-order-row">
                  <span className="confirm-order-label">Quantity</span>
                  <span className="confirm-order-value">{order.quantity}</span>
                </div>
                <div className="confirm-order-row">
                  <span className="confirm-order-label">Unit Price</span>
                  <span className="confirm-order-value">PKR {Number(order.unit_price).toLocaleString('en-PK', { minimumFractionDigits: 2 })}</span>
                </div>
                <div className="confirm-order-row confirm-order-row-total">
                  <span className="confirm-order-label">Total Paid</span>
                  <span className="confirm-order-value confirm-order-total">PKR {Number(order.total_amount).toLocaleString('en-PK', { minimumFractionDigits: 2 })}</span>
                </div>
              </div>

              {/* Warning notice */}
              <div className="confirm-order-notice confirm-order-notice-warning">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                  <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                </svg>
                This action is irreversible. {order.buyer_protection_enabled
                  ? 'Seller payout will be held by buyer protection for 14 days.'
                  : 'Funds will be released to the seller immediately.'}
              </div>

              <div className="confirm-order-notice">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"/>
                  <line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
                </svg>
                Only confirm if you have received and verified the delivered item.
              </div>
            </div>

            <div className="confirm-order-actions">
              <button className="btn btn-outline" onClick={() => setConfirmModal(false)} disabled={actionLoading}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleConfirm} disabled={actionLoading}>
                {actionLoading ? (
                  <><div className="loading-spinner" style={{ width: '16px', height: '16px', borderWidth: '2px' }}></div> Processing...</>
                ) : (
                  '✅ Yes, Confirm Received'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

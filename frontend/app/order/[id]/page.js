'use client';

import { useState, useEffect, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getOrderDetail, confirmOrder, disputeOrder, deliverOrder, refundOrder, createReview } from '@/lib/api';
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
  const [reviewRating, setReviewRating] = useState(0);
  const [reviewHover, setReviewHover] = useState(0);
  const [reviewComment, setReviewComment] = useState('');
  const [reviewSubmitted, setReviewSubmitted] = useState(false);
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
    doAction(async () => {
      await confirmOrder(id);
      setSuccess('Order confirmed! Funds released to seller.');
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
      await createReview(id, reviewRating, reviewComment);
      setReviewSubmitted(true);
      setSuccess('Review submitted! Thank you for your feedback.');
      await loadOrder();
    } catch (err) {
      setError(err.message);
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

  return (
    <div className="container">
      {/* Breadcrumb */}
      <div className="page-header">
        <div className="breadcrumb">
          <Link href={isSeller ? '/sales' : '/orders'}>{isSeller ? 'Sales' : 'Purchases'}</Link>
          <span className="breadcrumb-sep">›</span>
          <span>Order #{order.id}</span>
        </div>
      </div>

      {success && <div className="alert alert-success">{success}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      <div className="order-detail-layout">
        {/* Left: Order Info */}
        <div className="order-detail-main">
          <div className="order-detail-header">
            <h1 className="order-detail-title">Order #{order.id}</h1>
            <span
              className="order-detail-status"
              style={{ background: getStatusColor(order.status) + '20', color: getStatusColor(order.status) }}
            >
              {getStatusIcon(order.status)} {order.status_display}
            </span>
          </div>

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
              {isBuyer && (order.status === 'pending' || order.status === 'delivered') && (
                <>
                  {order.status === 'delivered' && (
                  <button
                    className="btn btn-primary"
                    onClick={handleConfirm}
                    disabled={actionLoading}
                  >
                    {actionLoading ? 'Processing...' : '✅ Confirm Received'}
                  </button>
                  )}
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
              {order.status === 'completed' && (
                <div className="order-completed-msg" style={{ padding: '12px 0' }}>
                  ✅ This order has been completed. {isSeller ? 'Funds have been credited to your wallet.' : 'Thank you for your purchase!'}
                </div>
              )}
              {order.status === 'cancelled' && (
                <div style={{ color: 'var(--text-tertiary)', padding: '12px 0' }}>
                  ❌ This order has been cancelled and the buyer was refunded.
                </div>
              )}
            </div>
          </div>

          {/* Review Section — Buyer can review completed orders */}
          {isBuyer && order.status === 'completed' && !order.has_review && !reviewSubmitted && (
            <div className="order-detail-actions">
              <h3 className="order-detail-section-title">⭐ Leave a Review</h3>
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
                <button type="submit" className="btn btn-primary" disabled={reviewRating === 0}>
                  Submit Review
                </button>
              </form>
            </div>
          )}
          {isBuyer && (order.has_review || reviewSubmitted) && (
            <div className="order-detail-actions">
              <div className="order-completed-msg" style={{ padding: '8px 0' }}>
                ⭐ You've reviewed this order. Thank you!
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
              <span>Deliver Order #{order.id}</span>
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
    </div>
  );
}

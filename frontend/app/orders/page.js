'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getMyOrders, confirmOrder, disputeOrder } from '@/lib/api';

const ORDER_PAGE_SIZE = 20;

export default function OrdersPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [orders, setOrders] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loadingOrders, setLoadingOrders] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [actionLoading, setActionLoading] = useState(null);
  const [disputeModal, setDisputeModal] = useState(null);
  const [disputeReason, setDisputeReason] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    if (!loading && !user) router.push('/login');
  }, [user, loading, router]);

  useEffect(() => {
    if (user) loadOrders();
  }, [user]);

  async function loadOrders({ append = false, offset = 0 } = {}) {
    if (append) {
      setLoadingMore(true);
    } else {
      setLoadingOrders(true);
    }
    try {
      const data = await getMyOrders({ limit: ORDER_PAGE_SIZE, offset });
      setOrders(prev => append ? [...prev, ...(data.orders || [])] : (data.orders || []));
      setPagination(data.pagination || null);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingOrders(false);
      setLoadingMore(false);
    }
  }

  async function handleConfirm(orderId) {
    setError('');
    setSuccess('');
    setActionLoading(orderId);
    try {
      await confirmOrder(orderId);
      setSuccess('Order confirmed! Funds released to seller.');
      await loadOrders();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading(null);
    }
  }

  async function handleDispute(orderId) {
    if (!disputeReason.trim()) return;
    setError('');
    setSuccess('');
    setActionLoading(orderId);
    try {
      await disputeOrder(orderId, disputeReason);
      setSuccess('Dispute opened. Admin will review your case.');
      setDisputeModal(null);
      setDisputeReason('');
      await loadOrders();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading(null);
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

  if (loading || !user) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  return (
    <div className="container">
      <div className="page-header">
        <h1 className="page-title">🛍️ My Purchases</h1>
        <p className="page-subtitle">Track your purchases</p>
      </div>

      {success && <div className="alert alert-success">{success}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {loadingOrders ? (
        <div className="loading"><div className="loading-spinner"></div> Loading orders...</div>
      ) : orders.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">🛒</div>
          <p>No purchases yet. Browse listings to make your first purchase!</p>
        </div>
      ) : (
        <div className="orders-list">
          {orders.map((order) => (
            <div key={order.id} className={`order-card order-status-${order.status}`}>
              <div className="order-card-header">
                <div className="order-card-id">
                  <span className="order-hash">
                    <Link href={`/order/${order.id}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                      Order #{order.id}
                    </Link>
                  </span>
                  <span className={`status-pill order-pill-${order.status}`}>
                    {getStatusIcon(order.status)} {order.status_display}
                  </span>
                </div>
                <div className="order-card-date">
                  {new Date(order.created_at).toLocaleDateString('en-PK', {
                    day: 'numeric', month: 'short', year: 'numeric',
                  })}
                </div>
              </div>

              <div className="order-card-body">
                <div className="order-card-info">
                  <div className="order-card-title">{order.listing_title}</div>
                  <div className="order-card-meta">
                    <span>Seller: <Link href={`/seller/${order.seller_name}`} style={{ color: 'var(--green-600)', fontWeight: 600 }}>{order.seller_name}</Link></span>
                    <span>Qty: {order.quantity}</span>
                    <span>Unit: PKR {order.unit_price}</span>
                  </div>
                  {order.delivery_note && (
                    <div className="order-delivery-note">
                      <strong>📝 Delivery Note:</strong> {order.delivery_note}
                    </div>
                  )}
                  {order.dispute_reason && (
                    <div className="order-dispute-note">
                      <strong>⚠️ Dispute:</strong> {order.dispute_reason}
                    </div>
                  )}
                </div>
                <div className="order-card-price">
                  <div className="order-total">PKR {order.total_amount}</div>
                </div>
              </div>

              {/* Action buttons */}
              <div className="order-card-actions">
                <Link href={`/order/${order.id}`} className="btn btn-outline btn-sm">
                  📋 View Order
                </Link>
                {(order.status === 'pending' || order.status === 'delivered') && (
                  <>
                    {order.status === 'delivered' && (
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => handleConfirm(order.id)}
                      disabled={actionLoading === order.id}
                    >
                      {actionLoading === order.id ? 'Processing...' : '✅ Confirm Received'}
                    </button>
                    )}
                    <button
                      className="btn btn-outline btn-sm"
                      onClick={() => { setDisputeModal(order.id); setDisputeReason(''); }}
                      disabled={actionLoading === order.id}
                    >
                      ⚠️ Open Dispute
                    </button>
                  </>
                )}
                {order.status === 'completed' && (
                  <span className="order-completed-msg">✅ Order completed successfully</span>
                )}
              </div>
            </div>
          ))}
          {pagination?.next_offset !== null && pagination?.next_offset !== undefined && (
            <button
              className="btn btn-outline btn-full"
              onClick={() => loadOrders({ append: true, offset: pagination.next_offset })}
              disabled={loadingMore}
            >
              {loadingMore ? 'Loading...' : 'Load More Purchases'}
            </button>
          )}
        </div>
      )}

      {/* Dispute Modal */}
      {disputeModal && (
        <div className="image-preview-overlay" onClick={() => setDisputeModal(null)}>
          <div className="image-preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="image-preview-header">
              <span>Open Dispute</span>
              <button className="image-preview-close" onClick={() => setDisputeModal(null)}>✕</button>
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
                <button className="btn btn-outline" onClick={() => setDisputeModal(null)}>Cancel</button>
                <button
                  className="btn btn-primary"
                  onClick={() => handleDispute(disputeModal)}
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

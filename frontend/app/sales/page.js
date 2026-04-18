'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getMySales, deliverOrder } from '@/lib/api';

export default function SalesPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [sales, setSales] = useState([]);
  const [loadingSales, setLoadingSales] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);
  const [deliverModal, setDeliverModal] = useState(null);
  const [deliveryNote, setDeliveryNote] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    if (!loading && !user) router.push('/login');
    if (!loading && user && !user.is_seller) router.push('/dashboard');
  }, [user, loading, router]);

  useEffect(() => {
    if (user && user.is_seller) loadSales();
  }, [user]);

  async function loadSales() {
    try {
      const data = await getMySales();
      setSales(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingSales(false);
    }
  }

  async function handleDeliver(orderId) {
    setError('');
    setSuccess('');
    setActionLoading(orderId);
    try {
      await deliverOrder(orderId, deliveryNote);
      setSuccess('Order marked as delivered!');
      setDeliverModal(null);
      setDeliveryNote('');
      await loadSales();
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

  if (!user.is_seller) return null;

  const pendingCount = sales.filter(s => s.status === 'pending').length;
  const completedCount = sales.filter(s => s.status === 'completed').length;
  const totalRevenue = sales
    .filter(s => s.status === 'completed')
    .reduce((sum, s) => sum + parseFloat(s.seller_amount), 0);

  return (
    <div className="container">
      <div className="page-header">
        <h1 className="page-title">💼 My Sales</h1>
        <p className="page-subtitle">Manage your sales and deliveries</p>
      </div>

      {/* Sales Stats */}
      <div className="dashboard-stats">
        <div className="stat-card">
          <div className="stat-icon">⏳</div>
          <div className="stat-info">
            <div className="stat-value">{pendingCount}</div>
            <div className="stat-label">Pending Deliveries</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon">✅</div>
          <div className="stat-info">
            <div className="stat-value">{completedCount}</div>
            <div className="stat-label">Completed Sales</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon">💰</div>
          <div className="stat-info">
            <div className="stat-value">PKR {totalRevenue.toLocaleString('en-PK', { minimumFractionDigits: 2 })}</div>
            <div className="stat-label">Total Revenue</div>
          </div>
        </div>
      </div>

      {success && <div className="alert alert-success">{success}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {loadingSales ? (
        <div className="loading"><div className="loading-spinner"></div> Loading sales...</div>
      ) : sales.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">💼</div>
          <p>No sales yet. When buyers purchase your listings, they'll appear here.</p>
        </div>
      ) : (
        <div className="orders-list">
          {sales.map((sale) => (
            <div key={sale.id} className={`order-card order-status-${sale.status}`}>
              <div className="order-card-header">
                <div className="order-card-id">
                  <span className="order-hash">
                    <Link href={`/order/${sale.id}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                      Sale #{sale.id}
                    </Link>
                  </span>
                  <span className={`status-pill order-pill-${sale.status}`}>
                    {getStatusIcon(sale.status)} {sale.status_display}
                  </span>
                </div>
                <div className="order-card-date">
                  {new Date(sale.created_at).toLocaleDateString('en-PK', {
                    day: 'numeric', month: 'short', year: 'numeric',
                  })}
                </div>
              </div>

              <div className="order-card-body">
                <div className="order-card-info">
                  <div className="order-card-title">{sale.listing_title}</div>
                  <div className="order-card-meta">
                    <span>Buyer: <strong>{sale.buyer_name}</strong></span>
                    <span>Qty: {sale.quantity}</span>
                    <span>Commission: {sale.commission_rate}%</span>
                  </div>
                  {sale.delivery_note && (
                    <div className="order-delivery-note">
                      <strong>📝 Delivery Note:</strong> {sale.delivery_note}
                    </div>
                  )}
                  {sale.dispute_reason && (
                    <div className="order-dispute-note">
                      <strong>⚠️ Dispute:</strong> {sale.dispute_reason}
                    </div>
                  )}
                </div>
                <div className="order-card-price">
                  <div className="order-total">PKR {sale.seller_amount}</div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)' }}>
                    of PKR {sale.total_amount}
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="order-card-actions">
                <Link href={`/order/${sale.id}`} className="btn btn-outline btn-sm">
                  📋 View Order
                </Link>
                {sale.status === 'pending' && (
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => { setDeliverModal(sale.id); setDeliveryNote(''); }}
                    disabled={actionLoading === sale.id}
                  >
                    📦 Deliver
                  </button>
                )}
                {sale.status === 'delivered' && (
                  <span className="order-completed-msg" style={{ color: 'var(--text-tertiary)' }}>
                    ⏳ Waiting for buyer to confirm
                  </span>
                )}
                {sale.status === 'completed' && (
                  <span className="order-completed-msg">✅ Funds received</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Deliver Modal */}
      {deliverModal && (
        <div className="image-preview-overlay" onClick={() => setDeliverModal(null)}>
          <div className="image-preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="image-preview-header">
              <span>Deliver Sale #{deliverModal}</span>
              <button className="image-preview-close" onClick={() => setDeliverModal(null)}>✕</button>
            </div>
            <div style={{ padding: '20px' }}>
              <div className="form-group">
                <label className="form-label">Delivery Details (optional)</label>
                <textarea
                  className="form-textarea"
                  value={deliveryNote}
                  onChange={(e) => setDeliveryNote(e.target.value)}
                  placeholder="Account credentials, activation code, download link, etc..."
                  rows={4}
                />
              </div>
              <div style={{ display: 'flex', gap: '10px', marginTop: '16px', justifyContent: 'flex-end' }}>
                <button className="btn btn-outline" onClick={() => setDeliverModal(null)}>Cancel</button>
                <button
                  className="btn btn-primary"
                  onClick={() => handleDeliver(deliverModal)}
                  disabled={actionLoading}
                >
                  {actionLoading ? 'Delivering...' : '📦 Mark as Delivered'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

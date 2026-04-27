'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getSellerDashboard } from '@/lib/api';

function formatPKR(value) {
  const num = Number(value);
  if (isNaN(num)) return 'PKR 0';
  return `PKR ${num.toLocaleString('en-PK', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function formatPKRDecimal(value) {
  const num = Number(value);
  if (isNaN(num)) return 'PKR 0.00';
  return `PKR ${num.toLocaleString('en-PK', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function timeAgo(dateStr) {
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

function MiniSparkline({ data, width = 140, height = 40 }) {
  if (!data || data.length === 0) {
    return (
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="sd-sparkline">
        <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="var(--border-color)" strokeWidth="1" strokeDasharray="4 2" />
      </svg>
    );
  }

  const values = data.map(d => Number(d.revenue));
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const padding = 2;
  const usableWidth = width - padding * 2;
  const usableHeight = height - padding * 2;

  const points = values.map((v, i) => {
    const x = padding + (i / Math.max(values.length - 1, 1)) * usableWidth;
    const y = padding + usableHeight - ((v - min) / range) * usableHeight;
    return `${x},${y}`;
  }).join(' ');

  const areaPoints = `${padding},${height - padding} ${points} ${padding + usableWidth},${height - padding}`;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="sd-sparkline">
      <defs>
        <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--green-400)" stopOpacity="0.3" />
          <stop offset="100%" stopColor="var(--green-400)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={areaPoints} fill="url(#sparkGrad)" />
      <polyline points={points} fill="none" stroke="var(--green-500)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function RatingStars({ rating, size = 16 }) {
  const stars = [];
  const full = Math.floor(rating);
  const hasHalf = rating - full >= 0.3;
  for (let i = 0; i < 5; i++) {
    if (i < full) {
      stars.push(<span key={i} className="sd-star sd-star-full" style={{ fontSize: size }}>★</span>);
    } else if (i === full && hasHalf) {
      stars.push(<span key={i} className="sd-star sd-star-half" style={{ fontSize: size }}>★</span>);
    } else {
      stars.push(<span key={i} className="sd-star sd-star-empty" style={{ fontSize: size }}>★</span>);
    }
  }
  return <span className="sd-stars">{stars}</span>;
}

function RatingBar({ label, count, total, color }) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <div className="sd-rating-bar-row">
      <span className="sd-rating-bar-label">{label}★</span>
      <div className="sd-rating-bar-track">
        <div className="sd-rating-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="sd-rating-bar-count">{count}</span>
    </div>
  );
}

const ORDER_STATUS_STYLES = {
  pending: { icon: '⏳', color: '#f59e0b', bg: '#fffbeb' },
  delivered: { icon: '📦', color: '#3b82f6', bg: '#eff6ff' },
  completed: { icon: '✅', color: '#22c55e', bg: '#f0fdf4' },
  disputed: { icon: '⚠️', color: '#ef4444', bg: '#fef2f2' },
  cancelled: { icon: '❌', color: '#6b7280', bg: '#f9fafb' },
};

export default function DashboardPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!loading && !user) {
      router.push('/login');
      return;
    }
    if (user && !user.is_seller) {
      router.replace('/');
      return;
    }
    if (user && user.is_seller) {
      getSellerDashboard()
        .then(setData)
        .catch(err => setError(err.message));
    }
  }, [user, loading, router]);

  if (loading || !user) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  if (!user.is_seller) {
    return null; // Will redirect
  }

  if (error) {
    return (
      <div className="container">
        <div className="sd-error">
          <p>Failed to load dashboard: {error}</p>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>Retry</button>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="container">
        <div className="sd-loading">
          <div className="loading-spinner"></div>
          <p>Loading your seller dashboard...</p>
        </div>
      </div>
    );
  }

  const { orders, revenue, daily_revenue, listings, reviews, recent_sales, top_categories, wallet_balance } = data;

  return (
    <div className="container">
      {/* Header */}
      <div className="sd-header">
        <div className="sd-header-left">
          <h1 className="sd-title">Seller Dashboard</h1>
          <p className="sd-subtitle">Welcome back, <strong>{user.username}</strong></p>
        </div>
        <div className="sd-header-actions">
          <Link href="/dashboard/create-listing" className="btn btn-primary sd-create-btn" id="sd-create-listing">
            <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16"><path fillRule="evenodd" d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 11-2 0v-3H6a1 1 0 110-2h3V6a1 1 0 011-1z" clipRule="evenodd" /></svg>
            New Listing
          </Link>
        </div>
      </div>

      {/* Primary Metric Cards */}
      <div className="sd-metrics-grid">
        <Link href="/wallet" className="sd-metric-card sd-metric-wallet" id="sd-wallet-card">
          <div className="sd-metric-icon-wrap sd-icon-green">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="22" height="22"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><path d="M1 10h22" strokeLinecap="round"/></svg>
          </div>
          <div className="sd-metric-content">
            <span className="sd-metric-label">Wallet Balance</span>
            <span className="sd-metric-value">{formatPKRDecimal(wallet_balance)}</span>
          </div>
        </Link>

        <div className="sd-metric-card sd-metric-revenue" id="sd-revenue-card">
          <div className="sd-metric-icon-wrap sd-icon-emerald">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="22" height="22"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </div>
          <div className="sd-metric-content">
            <span className="sd-metric-label">Total Revenue</span>
            <span className="sd-metric-value">{formatPKR(revenue.total)}</span>
          </div>
          <MiniSparkline data={daily_revenue} />
        </div>

        <Link href="/sales" className="sd-metric-card sd-metric-orders" id="sd-orders-card">
          <div className="sd-metric-icon-wrap sd-icon-blue">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="22" height="22"><path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z" strokeLinecap="round" strokeLinejoin="round"/><path d="M3 6h18" strokeLinecap="round"/><path d="M16 10a4 4 0 01-8 0" strokeLinecap="round"/></svg>
          </div>
          <div className="sd-metric-content">
            <span className="sd-metric-label">Total Sales</span>
            <span className="sd-metric-value">{orders.completed}</span>
          </div>
          <div className="sd-metric-sub">
            {orders.pending > 0 && <span className="sd-metric-badge sd-badge-amber">{orders.pending} pending</span>}
            {orders.delivered > 0 && <span className="sd-metric-badge sd-badge-blue">{orders.delivered} delivered</span>}
          </div>
        </Link>

        <Link href="/my-listings" className="sd-metric-card sd-metric-listings" id="sd-listings-card">
          <div className="sd-metric-icon-wrap sd-icon-purple">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="22" height="22"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" strokeLinecap="round" strokeLinejoin="round"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </div>
          <div className="sd-metric-content">
            <span className="sd-metric-label">Active Listings</span>
            <span className="sd-metric-value">{listings.active_listings}</span>
          </div>
          <div className="sd-metric-sub">
            <span className="sd-metric-badge sd-badge-gray">{listings.total_listings} total</span>
          </div>
        </Link>
      </div>

      {/* Revenue Period Cards */}
      <div className="sd-period-row">
        <div className="sd-period-card" id="sd-week-revenue">
          <div className="sd-period-header">
            <span className="sd-period-dot sd-dot-green"></span>
            <span>Last 7 Days</span>
          </div>
          <div className="sd-period-value">{formatPKR(revenue.week)}</div>
          <div className="sd-period-orders">{revenue.week_orders} orders</div>
        </div>
        <div className="sd-period-card" id="sd-month-revenue">
          <div className="sd-period-header">
            <span className="sd-period-dot sd-dot-blue"></span>
            <span>Last 30 Days</span>
          </div>
          <div className="sd-period-value">{formatPKR(revenue.month)}</div>
          <div className="sd-period-orders">{revenue.month_orders} orders</div>
        </div>
        <div className="sd-period-card" id="sd-commission-total">
          <div className="sd-period-header">
            <span className="sd-period-dot sd-dot-amber"></span>
            <span>Commission Paid</span>
          </div>
          <div className="sd-period-value">{formatPKR(revenue.total_commission)}</div>
          <div className="sd-period-orders">from {formatPKR(revenue.total_gross)} gross</div>
        </div>
      </div>

      {/* Two Column Layout */}
      <div className="sd-two-col">
        {/* Left: Recent Sales */}
        <div className="sd-panel" id="sd-recent-sales">
          <div className="sd-panel-header">
            <h2 className="sd-panel-title">Recent Activity</h2>
            <Link href="/sales" className="sd-panel-link">View all →</Link>
          </div>
          <div className="sd-panel-body">
            {recent_sales.length === 0 ? (
              <div className="sd-empty">
                <div className="sd-empty-icon">📦</div>
                <p>No sales yet. Create your first listing to get started!</p>
              </div>
            ) : (
              <div className="sd-activity-list">
                {recent_sales.map(sale => {
                  const style = ORDER_STATUS_STYLES[sale.status] || ORDER_STATUS_STYLES.pending;
                  return (
                    <Link key={sale.id} href={`/order/${sale.id}`} className="sd-activity-item">
                      <div className="sd-activity-icon" style={{ background: style.bg, color: style.color }}>
                        {style.icon}
                      </div>
                      <div className="sd-activity-info">
                        <div className="sd-activity-title">{sale.listing_title}</div>
                        <div className="sd-activity-meta">
                          <span className="sd-activity-buyer">{sale.buyer_name}</span>
                          <span className="sd-activity-time">{timeAgo(sale.created_at)}</span>
                        </div>
                      </div>
                      <div className="sd-activity-amount">
                        <span className="sd-activity-price">{formatPKR(sale.total_amount)}</span>
                        <span className="sd-activity-status" style={{ color: style.color }}>{sale.status_display}</span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right: Reviews & Categories */}
        <div className="sd-right-col">
          {/* Reviews Summary */}
          <div className="sd-panel" id="sd-reviews-panel">
            <div className="sd-panel-header">
              <h2 className="sd-panel-title">Reviews</h2>
              <Link href={`/seller/${user.username}`} className="sd-panel-link">View profile →</Link>
            </div>
            <div className="sd-panel-body">
              {reviews.total === 0 ? (
                <div className="sd-empty sd-empty-sm">
                  <p>No reviews yet</p>
                </div>
              ) : (
                <div className="sd-reviews-summary">
                  <div className="sd-reviews-big">
                    <span className="sd-reviews-number">{reviews.avg_rating}</span>
                    <RatingStars rating={reviews.avg_rating} size={18} />
                    <span className="sd-reviews-count">{reviews.total} review{reviews.total !== 1 ? 's' : ''}</span>
                  </div>
                  <div className="sd-rating-bars">
                    <RatingBar label="5" count={reviews.distribution['5']} total={reviews.total} color="#22c55e" />
                    <RatingBar label="4" count={reviews.distribution['4']} total={reviews.total} color="#4ade80" />
                    <RatingBar label="3" count={reviews.distribution['3']} total={reviews.total} color="#fbbf24" />
                    <RatingBar label="2" count={reviews.distribution['2']} total={reviews.total} color="#f97316" />
                    <RatingBar label="1" count={reviews.distribution['1']} total={reviews.total} color="#ef4444" />
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Top Categories */}
          {top_categories.length > 0 && (
            <div className="sd-panel" id="sd-top-categories">
              <div className="sd-panel-header">
                <h2 className="sd-panel-title">Top Categories</h2>
              </div>
              <div className="sd-panel-body">
                <div className="sd-category-list">
                  {top_categories.map((cat, i) => (
                    <div key={i} className="sd-category-item">
                      <div className="sd-category-rank">#{i + 1}</div>
                      <div className="sd-category-info">
                        <div className="sd-category-name">{cat.game} — {cat.category}</div>
                        <div className="sd-category-stats">{cat.sales_count} sales · {formatPKR(cat.revenue)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Order Status Breakdown */}
          <div className="sd-panel" id="sd-order-breakdown">
            <div className="sd-panel-header">
              <h2 className="sd-panel-title">Order Status</h2>
            </div>
            <div className="sd-panel-body">
              <div className="sd-status-grid">
                {[
                  { key: 'pending', label: 'Pending', count: orders.pending },
                  { key: 'delivered', label: 'Delivered', count: orders.delivered },
                  { key: 'completed', label: 'Completed', count: orders.completed },
                  { key: 'disputed', label: 'Disputed', count: orders.disputed },
                ].map(item => {
                  const style = ORDER_STATUS_STYLES[item.key];
                  return (
                    <div key={item.key} className="sd-status-item">
                      <div className="sd-status-icon" style={{ background: style.bg, color: style.color }}>{style.icon}</div>
                      <span className="sd-status-count">{item.count}</span>
                      <span className="sd-status-label">{item.label}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Quick Actions Footer */}
      <div className="sd-quick-actions">
        <Link href="/dashboard/create-listing" className="sd-action-card" id="sd-action-create">
          <span className="sd-action-icon">📝</span>
          <span className="sd-action-label">Create Listing</span>
        </Link>
        <Link href="/my-listings" className="sd-action-card" id="sd-action-listings">
          <span className="sd-action-icon">📋</span>
          <span className="sd-action-label">My Listings</span>
        </Link>
        <Link href="/sales" className="sd-action-card" id="sd-action-sales">
          <span className="sd-action-icon">💼</span>
          <span className="sd-action-label">My Sales</span>
        </Link>
        <Link href="/wallet" className="sd-action-card" id="sd-action-wallet">
          <span className="sd-action-icon">💰</span>
          <span className="sd-action-label">Wallet</span>
        </Link>
        <Link href="/inbox" className="sd-action-card" id="sd-action-inbox">
          <span className="sd-action-icon">💬</span>
          <span className="sd-action-label">Messages</span>
        </Link>
        <Link href={`/seller/${user.username}`} className="sd-action-card" id="sd-action-profile">
          <span className="sd-action-icon">👤</span>
          <span className="sd-action-label">Public Profile</span>
        </Link>
      </div>
    </div>
  );
}

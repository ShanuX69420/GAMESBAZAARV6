'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getMySales } from '@/lib/api';
import { orderLabel, orderPath } from '@/lib/orderNumbers';

const SALES_PAGE_SIZE = 20;

const STATUS_TABS = [
  { key: '', label: 'All Sales', icon: '📋' },
  { key: 'pending', label: 'Awaiting Delivery', icon: '⏳' },
  { key: 'delivered', label: 'Delivered', icon: '📦' },
  { key: 'completed', label: 'Completed', icon: '✅' },
  { key: 'disputed', label: 'Disputed', icon: '⚠️' },
  { key: 'cancelled', label: 'Cancelled', icon: '❌' },
];

export default function SalesPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [sales, setSales] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [statusCounts, setStatusCounts] = useState({});
  const [loadingSales, setLoadingSales] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  // Filter state
  const [statusFilter, setStatusFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const latestRequestId = useRef(0);

  useEffect(() => {
    if (!loading && !user) router.push('/login');
    if (!loading && user && !user.is_seller) router.push('/dashboard');
  }, [user, loading, router]);

  const loadSales = useCallback(async ({ append = false, beforeId = null } = {}) => {
    const requestId = ++latestRequestId.current;
    if (append) {
      setLoadingMore(true);
    } else {
      setLoadingSales(true);
    }
    try {
      const data = await getMySales({
        limit: SALES_PAGE_SIZE,
        beforeId,
        cursor: true,
        status: statusFilter || undefined,
        search: debouncedSearchQuery || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      if (requestId !== latestRequestId.current) return;
      setSales(prev => append ? [...prev, ...(data.sales || [])] : (data.sales || []));
      setPagination(data.pagination || null);
      if (data.status_counts) setStatusCounts(data.status_counts);
    } catch (err) {
      if (requestId === latestRequestId.current) console.error(err);
    } finally {
      if (requestId === latestRequestId.current) {
        setLoadingSales(false);
        setLoadingMore(false);
      }
    }
  }, [statusFilter, debouncedSearchQuery, dateFrom, dateTo]);

  useEffect(() => {
    if (user && user.is_seller) loadSales();
  }, [user, loadSales]);

  function handleSearchChange(e) {
    const val = e.target.value;
    setSearchQuery(val);
  }

  // Debounce search
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      setDebouncedSearchQuery(searchQuery.trim());
    }, 300);
    return () => clearTimeout(timeoutId);
  }, [searchQuery]);

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

  function formatDateTime(isoString) {
    const d = new Date(isoString);
    return d.toLocaleDateString('en-PK', {
      day: 'numeric', month: 'short', year: 'numeric',
    }) + ', ' + d.toLocaleTimeString('en-PK', {
      hour: '2-digit', minute: '2-digit', hour12: true,
    });
  }

  function clearFilters() {
    setStatusFilter('');
    setSearchQuery('');
    setDebouncedSearchQuery('');
    setDateFrom('');
    setDateTo('');
  }

  const hasActiveFilters = statusFilter || searchQuery || dateFrom || dateTo;

  if (loading || !user) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  if (!user.is_seller) return null;

  return (
    <div className="container">
      <div className="page-header">
        <h1 className="page-title">💼 My Sales</h1>
        <p className="page-subtitle">View your sales and order status</p>
      </div>

      {/* Filter Toolbar */}
      <div className="orders-filter-toolbar">
        {/* Status Tabs */}
        <div className="orders-status-tabs">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.key}
              className={`orders-status-tab ${statusFilter === tab.key ? 'active' : ''}`}
              onClick={() => setStatusFilter(tab.key)}
            >
              <span className="orders-tab-icon">{tab.icon}</span>
              <span className="orders-tab-label">{tab.label}</span>
              {['pending', 'delivered', 'disputed'].includes(tab.key) && statusCounts[tab.key] > 0 && (
                <span className="orders-tab-count">{statusCounts[tab.key]}</span>
              )}
            </button>
          ))}
        </div>

        {/* Search & Date Filters */}
        <div className="orders-filter-row">
          <div className="orders-search-wrap">
            <span className="orders-search-icon">🔍</span>
            <input
              type="text"
              className="orders-search-input"
              placeholder="Search by title or buyer..."
              value={searchQuery}
              onChange={handleSearchChange}
            />
            {searchQuery && (
              <button
                className="orders-search-clear"
                onClick={() => {
                  setSearchQuery('');
                  setDebouncedSearchQuery('');
                }}
              >✕</button>
            )}
          </div>
          <div className="orders-date-filters">
            <div className="orders-date-field">
              <label className="orders-date-label">From</label>
              <input
                type="date"
                className="orders-date-input"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </div>
            <div className="orders-date-field">
              <label className="orders-date-label">To</label>
              <input
                type="date"
                className="orders-date-input"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </div>
          </div>
          {hasActiveFilters && (
            <button className="orders-clear-filters" onClick={clearFilters}>
              ✕ Clear All
            </button>
          )}
        </div>
      </div>

      {loadingSales ? (
        <div className="loading"><div className="loading-spinner"></div> Loading sales...</div>
      ) : sales.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">💼</div>
          <p>{hasActiveFilters ? 'No sales match your filters.' : 'No sales yet. When buyers purchase your listings, they\'ll appear here.'}</p>
          {hasActiveFilters && (
            <button className="btn btn-outline btn-sm" onClick={clearFilters} style={{ marginTop: 12 }}>
              Clear Filters
            </button>
          )}
        </div>
      ) : (
        <div className="orders-list">
          {sales.map((sale) => (
            <div key={sale.id} className={`order-card order-status-${sale.status}`}>
              <div className="order-card-header">
                <div className="order-card-id">
                  <span className="order-hash">
                    <Link href={orderPath(sale)} style={{ color: 'inherit', textDecoration: 'none' }}>
                      Sale {orderLabel(sale)}
                    </Link>
                  </span>
                  <span className={`status-pill order-pill-${sale.status}`}>
                    {getStatusIcon(sale.status)} {sale.status_display}
                  </span>
                </div>
                <div className="order-card-date">
                  {formatDateTime(sale.created_at)}
                </div>
              </div>

              <div className="order-card-body">
                <div className="order-card-info">
                  <div className="order-card-title">{sale.listing_title}</div>
                  <div className="order-card-meta">
                    <span>Buyer: <strong>{sale.buyer_name}</strong></span>
                    <span>Qty: {sale.quantity}</span>
                  </div>
                </div>
                <div className="order-card-price">
                  <div className="order-total">PKR {sale.seller_amount}</div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)' }}>
                    of PKR {sale.total_amount}
                  </div>
                </div>
              </div>

              {/* Details */}
              <div className="order-card-actions">
                <Link href={orderPath(sale)} className="btn btn-outline btn-sm">
                  📋 View Order
                </Link>
                {sale.status === 'delivered' && (
                  <span className="order-completed-msg" style={{ color: 'var(--text-tertiary)' }}>
                    ⏳ Waiting for buyer to confirm
                  </span>
                )}
              </div>
            </div>
          ))}
          {pagination?.next_before_id !== null && pagination?.next_before_id !== undefined && (
            <button
              className="btn btn-outline btn-full"
              onClick={() => loadSales({ append: true, beforeId: pagination.next_before_id })}
              disabled={loadingMore}
            >
              {loadingMore ? 'Loading...' : 'Load More Sales'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

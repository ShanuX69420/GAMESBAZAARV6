'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getHeldOrders } from '@/lib/api';

const HELD_ORDERS_PAGE_SIZE = 20;

export default function HeldBalancePage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [heldData, setHeldData] = useState(null);
  const [pagination, setPagination] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageLoading, setPageLoading] = useState(true);

  useEffect(() => {
    if (!loading && !user) router.push('/login');
  }, [user, loading, router]);

  useEffect(() => {
    if (user) {
      loadHeldOrders();
    }
  }, [user]);

  async function loadHeldOrders() {
    try {
      const data = await getHeldOrders({ limit: HELD_ORDERS_PAGE_SIZE, offset: 0 });
      setHeldData(data);
      setPagination(data.pagination || null);
    } catch (err) {
      console.error(err);
    } finally {
      setPageLoading(false);
    }
  }

  async function loadMore() {
    if (!pagination?.next_offset || loadingMore) return;
    setLoadingMore(true);
    try {
      const data = await getHeldOrders({
        limit: HELD_ORDERS_PAGE_SIZE,
        offset: pagination.next_offset,
      });
      setHeldData(prev => ({
        ...data,
        orders: [...(prev?.orders || []), ...(data.orders || [])],
      }));
      setPagination(data.pagination || null);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingMore(false);
    }
  }

  if (loading || !user) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  if (pageLoading) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading pending balance...</div>
      </div>
    );
  }

  const heldBalance = heldData ? Number(heldData.held_balance || 0) : 0;
  const heldOrderCount = heldData?.held_order_count || 0;
  const orders = heldData?.orders || [];

  return (
    <div className="container">
      {/* Breadcrumb */}
      <div className="held-breadcrumb">
        <Link href="/wallet" className="held-breadcrumb-link">Wallet</Link>
        <span className="held-breadcrumb-sep">›</span>
        <span className="held-breadcrumb-current">Pending Balance</span>
      </div>

      {/* Header with held balance */}
      <div className="held-header">
        <div className="held-header-left">
          <h1 className="held-page-title">Pending Balance</h1>
          <p className="held-page-subtitle">
            Some completed orders may stay pending while they finish processing.
          </p>
        </div>
        <div className="held-balance-badge">
          <div className="held-balance-amount">
            PKR {heldBalance.toLocaleString('en-PK', { minimumFractionDigits: 2 })}
          </div>
          <div className="held-balance-label">Pending Balance</div>
        </div>
      </div>

      {/* Stats Row */}
      <div className="held-stats-row">
        <div className="held-stat-card">
          <div className="held-stat-info">
            <div className="held-stat-value">{heldOrderCount}</div>
            <div className="held-stat-label">Pending Orders</div>
          </div>
        </div>
        <div className="held-stat-card">
          <div className="held-stat-info">
            <div className="held-stat-value">
              PKR {heldBalance.toLocaleString('en-PK', { minimumFractionDigits: 2 })}
            </div>
            <div className="held-stat-label">Total Pending</div>
          </div>
        </div>
        <div className="held-stat-card">
          <div className="held-stat-info">
            <div className="held-stat-value">
              {heldData?.next_release_at
                ? new Date(heldData.next_release_at).toLocaleDateString('en-PK', { day: 'numeric', month: 'short', year: 'numeric' })
                : '—'}
            </div>
            <div className="held-stat-label">Next Update</div>
          </div>
        </div>
      </div>

      {/* Orders Table */}
      {orders.length > 0 ? (
        <div className="held-orders-section">
          <div className="listings-table-wrap">
            <table className="listings-table held-orders-table">
              <thead>
                <tr>
                  <th>TRANSACTION DATE</th>
                  <th>ORDER</th>
                  <th>UPDATE</th>
                  <th>AMOUNT</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => {
                  const daysText = order.days_until_release !== null
                    ? `${order.days_until_release} day${order.days_until_release !== 1 ? 's' : ''}`
                    : '—';
                  return (
                    <tr key={order.id} className="held-order-row">
                      <td className="held-order-date">
                        {new Date(order.created_at).toLocaleDateString('en-PK', {
                          year: 'numeric',
                          month: 'short',
                          day: 'numeric',
                        })}
                        <span className="held-order-time">
                          {new Date(order.created_at).toLocaleTimeString('en-PK', {
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </span>
                      </td>
                      <td className="held-order-activity">
                        <Link href={`/order/${order.order_number}`} className="held-order-link">
                          {order.order_number}
                        </Link>
                        <span className="held-order-title">{order.listing_title}</span>
                      </td>
                      <td>
                        <span className="held-release-badge">
                          {daysText}
                        </span>
                      </td>
                      <td className="held-order-amount">
                        PKR {Number(order.seller_amount).toLocaleString('en-PK', { minimumFractionDigits: 2 })}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {pagination?.next_offset !== null && pagination?.next_offset !== undefined && (
            <button
              className="btn btn-outline btn-full"
              style={{ marginTop: '16px' }}
              onClick={loadMore}
              disabled={loadingMore}
            >
              {loadingMore ? 'Loading...' : 'Load More'}
            </button>
          )}
        </div>
      ) : (
        <div className="empty-state" style={{ marginTop: '40px' }}>
          <h3>No Pending Orders</h3>
          <p>You don't have any pending order balance at the moment.</p>
          <Link href="/wallet" className="btn btn-primary" style={{ marginTop: '12px' }}>
            ← Back to Wallet
          </Link>
        </div>
      )}
    </div>
  );
}

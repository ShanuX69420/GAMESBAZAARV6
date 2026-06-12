'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { getNotifications, markNotificationRead } from '@/lib/api';
import { notificationDestinationPath } from '@/lib/notifications';

const NOTIF_ICONS = {
  new_order: '🛒',
  order_delivered: '📦',
  order_confirmed: '✅',
  order_disputed: '⚠️',
  order_cancelled: '❌',
  new_review: '⭐',
  topup_approved: '💰',
  topup_rejected: '🚫',
  withdraw_approved: '💸',
  withdraw_rejected: '🚫',
  admin_message: '💬',
  item_request: '📨',
};

const NOTIF_LABELS = {
  new_order: 'New Order',
  order_delivered: 'Order Delivered',
  order_confirmed: 'Order Confirmed',
  order_disputed: 'Order Disputed',
  order_cancelled: 'Order Cancelled',
  new_review: 'New Review',
  topup_approved: 'Top-Up Approved',
  topup_rejected: 'Top-Up Rejected',
  withdraw_approved: 'Withdrawal Approved',
  withdraw_rejected: 'Withdrawal Rejected',
  admin_message: 'Admin Message',
  item_request: 'Item Request',
};

export default function NotificationsPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [pageLoading, setPageLoading] = useState(true);
  const [pagination, setPagination] = useState(null);

  const loadNotifications = useCallback(async (offset = 0) => {
    try {
      const data = await getNotifications({ limit: 20, offset });
      if (offset === 0) {
        setNotifications(data.notifications || []);
      } else {
        setNotifications(prev => [...prev, ...(data.notifications || [])]);
      }
      setUnreadCount(data.unread_count || 0);
      setPagination(data.pagination || null);
    } catch {
      /* ignore */
    } finally {
      setPageLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!loading && !user) {
      router.push('/login');
      return;
    }
    if (user) loadNotifications();
  }, [user, loading, router, loadNotifications]);

  async function handleMarkAllRead() {
    try {
      await markNotificationRead('all');
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
      setUnreadCount(0);
    } catch { /* ignore */ }
  }

  async function handleNotifClick(notif) {
    if (!notif.is_read) {
      try {
        await markNotificationRead(notif.id);
        setNotifications(prev => prev.map(n => n.id === notif.id ? { ...n, is_read: true } : n));
        setUnreadCount(prev => Math.max(0, prev - 1));
      } catch { /* ignore */ }
    }
    const destinationPath = notificationDestinationPath(notif);
    if (destinationPath) {
      router.push(destinationPath);
    }
  }

  function formatDate(dateStr) {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now - date;
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMs / 3600000);
    const diffDay = Math.floor(diffMs / 86400000);

    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;
    if (diffDay < 7) return `${diffDay}d ago`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  if (loading || pageLoading) {
    return (
      <main className="container" style={{ padding: '60px 16px', textAlign: 'center' }}>
        <div className="spinner"></div>
      </main>
    );
  }

  return (
    <main className="container notifications-page">
      <div className="notifications-header">
        <h1>Notifications</h1>
        {unreadCount > 0 && (
          <button className="notifications-mark-all" onClick={handleMarkAllRead}>
            Mark all as read ({unreadCount})
          </button>
        )}
      </div>

      {notifications.length === 0 ? (
        <div className="notifications-empty">
          <div className="notifications-empty-icon">🔔</div>
          <p>No notifications yet</p>
          <p className="text-secondary">You'll be notified about order updates, reviews, and more.</p>
        </div>
      ) : (
        <div className="notifications-list">
          {notifications.map((notif) => (
            <button
              key={notif.id}
              className={`notification-card ${!notif.is_read ? 'notification-card-unread' : ''}`}
              onClick={() => handleNotifClick(notif)}
            >
              <span className="notification-card-icon">
                {NOTIF_ICONS[notif.notification_type] || '🔔'}
              </span>
              <div className="notification-card-content">
                <div className="notification-card-top">
                  <span className="notification-card-type">
                    {NOTIF_LABELS[notif.notification_type] || notif.notification_type}
                  </span>
                  <span className="notification-card-time">{formatDate(notif.created_at)}</span>
                </div>
                <div className="notification-card-title">{notif.title}</div>
                {notif.message && (
                  <div className="notification-card-message">{notif.message}</div>
                )}
              </div>
              {!notif.is_read && <span className="notification-card-dot"></span>}
            </button>
          ))}

          {pagination && pagination.next_offset !== null && (
            <button
              className="notifications-load-more"
              onClick={() => loadNotifications(pagination.next_offset)}
            >
              Load more
            </button>
          )}
        </div>
      )}
    </main>
  );
}

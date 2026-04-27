'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { getUnreadCount, sendHeartbeat, searchMarketplace, getNotifications, markNotificationRead, getNotificationUnreadCount } from '@/lib/api';

const UNREAD_POLL_INTERVAL_MS = 15000;
const SEARCH_DEBOUNCE_MS = 300;
const NOTIF_POLL_INTERVAL_MS = 30000;

const NOTIF_ICONS = {
  new_order: '🛒',
  order_delivered: '📦',
  order_confirmed: '✅',
  order_disputed: '⚠️',
  order_cancelled: '❌',
  new_review: '⭐',
};

export default function Navbar() {
  const { user, loading, logout } = useAuth();
  const [unread, setUnread] = useState(0);
  const prevUnread = useRef(0);
  const router = useRouter();

  // ── Search state ───────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const searchRef = useRef(null);
  const mobileSearchRef = useRef(null);
  const debounceRef = useRef(null);
  const searchRequestRef = useRef(0);

  // ── Notification state ─────────────────────────────────────────────────
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifUnread, setNotifUnread] = useState(0);
  const [notifications, setNotifications] = useState([]);
  const [notifLoading, setNotifLoading] = useState(false);
  const notifRef = useRef(null);

  // ── Profile dropdown state ─────────────────────────────────────────────
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef(null);

  // ── Chat unread ────────────────────────────────────────────────────────
  const fetchUnread = useCallback(() => {
    if (!user) return;
    getUnreadCount().then(d => {
      const count = d.unread_count || 0;
      setUnread(count);
      if (count !== prevUnread.current) {
        prevUnread.current = count;
        window.dispatchEvent(new Event('chatUpdate'));
      }
    }).catch(() => {});
  }, [user]);

  useEffect(() => {
    if (!user) { setUnread(0); prevUnread.current = 0; return; }
    fetchUnread();
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') fetchUnread();
    }, UNREAD_POLL_INTERVAL_MS);
    const handleChatUpdate = () => fetchUnread();
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') fetchUnread();
    };
    window.addEventListener('chatUpdate', handleChatUpdate);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      clearInterval(interval);
      window.removeEventListener('chatUpdate', handleChatUpdate);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [user, fetchUnread]);

  // Heartbeat
  useEffect(() => {
    if (!user) return;
    sendHeartbeat();
    const hb = setInterval(() => sendHeartbeat(), 60000);
    return () => clearInterval(hb);
  }, [user]);

  // ── Notification polling ───────────────────────────────────────────────
  const fetchNotifCount = useCallback(() => {
    if (!user) return;
    getNotificationUnreadCount().then(d => {
      setNotifUnread(d.unread_count || 0);
    }).catch(() => {});
  }, [user]);

  useEffect(() => {
    if (!user) { setNotifUnread(0); return; }
    fetchNotifCount();
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') fetchNotifCount();
    }, NOTIF_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [user, fetchNotifCount]);

  const loadNotifications = useCallback(async () => {
    if (!user) return;
    setNotifLoading(true);
    try {
      const data = await getNotifications({ limit: 15 });
      setNotifications(data.notifications || []);
      setNotifUnread(data.unread_count || 0);
    } catch { /* ignore */ } finally { setNotifLoading(false); }
  }, [user]);

  function toggleNotifDropdown() {
    const newState = !notifOpen;
    setNotifOpen(newState);
    setProfileOpen(false);
    if (newState) loadNotifications();
  }

  function toggleProfileDropdown() {
    setProfileOpen(!profileOpen);
    setNotifOpen(false);
  }

  async function handleMarkAllRead() {
    try {
      await markNotificationRead('all');
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
      setNotifUnread(0);
    } catch { /* ignore */ }
  }

  async function handleNotifClick(notif) {
    if (!notif.is_read) {
      try {
        await markNotificationRead(notif.id);
        setNotifications(prev => prev.map(n => n.id === notif.id ? { ...n, is_read: true } : n));
        setNotifUnread(prev => Math.max(0, prev - 1));
      } catch { /* ignore */ }
    }
    setNotifOpen(false);
    if (notif.order_id) router.push(`/order/${notif.order_id}`);
  }

  // ── Search logic ──────────────────────────────────────────────────────
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const requestId = ++searchRequestRef.current;
    if (!searchQuery || searchQuery.length < 2) {
      setSearchResults(null);
      setSearchLoading(false);
      return;
    }
    setSearchLoading(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const data = await searchMarketplace(searchQuery);
        if (requestId === searchRequestRef.current) {
          setSearchResults(data);
          setSearchOpen(true);
        }
      } catch {
        if (requestId === searchRequestRef.current) setSearchResults(null);
      } finally {
        if (requestId === searchRequestRef.current) setSearchLoading(false);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [searchQuery]);

  // Close all dropdowns on outside click
  useEffect(() => {
    const handleClick = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target) &&
          mobileSearchRef.current && !mobileSearchRef.current.contains(e.target)) {
        setSearchOpen(false);
      }
      if (notifRef.current && !notifRef.current.contains(e.target)) {
        setNotifOpen(false);
      }
      if (profileRef.current && !profileRef.current.contains(e.target)) {
        setProfileOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  function clearSearch() {
    setSearchQuery('');
    setSearchResults(null);
    setSearchOpen(false);
  }

  function handleResultClick(e, item) {
    e.preventDefault();
    clearSearch();
    setProfileOpen(false);
    router.push(`/games/${item.game_slug}/${item.category_slug}`);
  }

  function timeAgo(dateStr) {
    const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
    return new Date(dateStr).toLocaleDateString();
  }

  const results = searchResults?.results || [];

  function renderSearchDropdown(isMobile = false) {
    if (!searchOpen || searchQuery.length < 2) return null;
    return (
      <div className={isMobile ? 'mobile-search-dropdown' : 'search-dropdown'}>
        {results.length === 0 && !searchLoading && (
          <div className="search-dropdown-empty">No results for &ldquo;{searchQuery}&rdquo;</div>
        )}
        {results.length > 0 && (
          <div className="search-dropdown-section">
            <div className="search-dropdown-section-title">Search Results</div>
            {results.map((item) => (
              <a key={item.id} href={`/games/${item.game_slug}/${item.category_slug}`}
                className="search-dropdown-item" onClick={(e) => handleResultClick(e, item)}>
                <span className="search-dropdown-item-icon">
                  {item.game_icon_url ? <img src={item.game_icon_url} alt="" className="search-dropdown-item-img" /> : '🎮'}
                </span>
                <span className="search-dropdown-item-label">{item.display_name}</span>
              </a>
            ))}
          </div>
        )}
      </div>
    );
  }

  // Get user initials for avatar
  function getInitials() {
    if (!user) return '?';
    return user.username.charAt(0).toUpperCase();
  }

  return (
    <>
      <nav className="navbar">
        <div className="container navbar-inner">
          {/* ── Left: Logo ── */}
          <Link href="/" className="navbar-logo">
            <div className="navbar-logo-icon">🎮</div>
            <span className="navbar-logo-text">GamesBazaar</span>
          </Link>

          {/* ── Center: Desktop Search ── */}
          <div className="navbar-search desktop-only" ref={searchRef}>
            <div className="navbar-search-form">
              <svg className="navbar-search-icon" viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" />
              </svg>
              <input type="text" className="navbar-search-input" placeholder="Search games, categories..."
                value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
                onFocus={() => { if (searchResults) setSearchOpen(true); }} id="navbar-search-input" />
              {searchLoading && <div className="navbar-search-spinner"></div>}
              {searchQuery && !searchLoading && (
                <button className="navbar-search-clear" onClick={clearSearch} type="button" aria-label="Clear search">✕</button>
              )}
            </div>
            {renderSearchDropdown(false)}
          </div>

          {/* ── Right: Nav actions ── */}
          <div className="navbar-actions">
            {!loading && (
              user ? (
                <>
                  {/* Desktop-only quick links */}
                  <div className="navbar-quick-links desktop-only">
                    <Link href="/orders" className="nav-quick-link">Purchases</Link>
                    {user.is_seller && <Link href="/sales" className="nav-quick-link">Sales</Link>}
                    <Link href="/wallet" className="nav-quick-link">Wallet</Link>
                  </div>

                  {/* Notification bell */}
                  <div className="nav-icon-wrapper" ref={notifRef}>
                    <button className="nav-icon-btn" onClick={toggleNotifDropdown} aria-label="Notifications" id="nav-notif-bell">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
                        <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" strokeLinecap="round" strokeLinejoin="round" />
                        <path d="M13.73 21a2 2 0 01-3.46 0" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      {notifUnread > 0 && <span className="nav-icon-badge">{notifUnread > 99 ? '99+' : notifUnread}</span>}
                    </button>

                    {notifOpen && (
                      <div className="notif-dropdown">
                        <div className="notif-dropdown-header">
                          <span className="notif-dropdown-title">Notifications</span>
                          {notifUnread > 0 && (
                            <button className="notif-mark-all-btn" onClick={handleMarkAllRead}>Mark all read</button>
                          )}
                        </div>
                        <div className="notif-dropdown-body">
                          {notifLoading && notifications.length === 0 && (
                            <div className="notif-dropdown-empty">Loading...</div>
                          )}
                          {!notifLoading && notifications.length === 0 && (
                            <div className="notif-dropdown-empty">No notifications yet</div>
                          )}
                          {notifications.map((notif) => (
                            <button key={notif.id} className={`notif-item ${!notif.is_read ? 'notif-item-unread' : ''}`}
                              onClick={() => handleNotifClick(notif)}>
                              <span className="notif-item-icon">{NOTIF_ICONS[notif.notification_type] || '🔔'}</span>
                              <div className="notif-item-content">
                                <div className="notif-item-title">{notif.title}</div>
                                <div className="notif-item-message">{notif.message}</div>
                                <div className="notif-item-time">{timeAgo(notif.created_at)}</div>
                              </div>
                              {!notif.is_read && <span className="notif-item-dot"></span>}
                            </button>
                          ))}
                        </div>
                        <Link href="/notifications" className="notif-dropdown-footer" onClick={() => setNotifOpen(false)}>
                          View all notifications
                        </Link>
                      </div>
                    )}
                  </div>

                  {/* Messages icon */}
                  <Link href="/inbox" className="nav-icon-btn nav-messages-icon" aria-label="Messages">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
                      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    {unread > 0 && <span className="nav-icon-badge">{unread > 99 ? '99+' : unread}</span>}
                  </Link>

                  {/* Profile avatar with dropdown */}
                  <div className="nav-icon-wrapper" ref={profileRef}>
                    <button className="nav-avatar-btn" onClick={toggleProfileDropdown} aria-label="Profile menu">
                      {user.avatar_url ? (
                        <img src={user.avatar_url} alt={user.username} className="nav-avatar nav-avatar-img" />
                      ) : (
                        <span className="nav-avatar">{getInitials()}</span>
                      )}
                    </button>

                    {profileOpen && (
                      <div className="profile-dropdown">
                        <div className="profile-dropdown-header">
                          {user.avatar_url ? (
                            <img src={user.avatar_url} alt={user.username} className="profile-dropdown-avatar profile-dropdown-avatar-img" />
                          ) : (
                            <span className="profile-dropdown-avatar">{getInitials()}</span>
                          )}
                          <div className="profile-dropdown-name">{user.username}</div>
                        </div>
                        <div className="profile-dropdown-body">
                          {/* Mobile-only links */}
                          <Link href="/orders" className="profile-dropdown-item mobile-only" onClick={() => setProfileOpen(false)}>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z" strokeLinecap="round" strokeLinejoin="round"/><path d="M3 6h18" strokeLinecap="round"/><path d="M16 10a4 4 0 01-8 0" strokeLinecap="round"/></svg>
                            Purchases
                          </Link>
                          {user.is_seller && (
                            <Link href="/sales" className="profile-dropdown-item mobile-only" onClick={() => setProfileOpen(false)}>
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6" strokeLinecap="round" strokeLinejoin="round"/></svg>
                              Sales
                            </Link>
                          )}
                          <Link href="/wallet" className="profile-dropdown-item mobile-only" onClick={() => setProfileOpen(false)}>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><path d="M1 10h22" strokeLinecap="round"/></svg>
                            Wallet
                          </Link>
                          <div className="profile-dropdown-divider mobile-only"></div>
                          {/* Common links */}
                          {user.is_seller && (
                            <Link href="/my-listings" className="profile-dropdown-item" onClick={() => setProfileOpen(false)}>
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" strokeLinecap="round" strokeLinejoin="round"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                              My Listings
                            </Link>
                          )}
                          {user.is_seller && (
                            <Link href="/dashboard" className="profile-dropdown-item" onClick={() => setProfileOpen(false)}>
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
                              Seller Dashboard
                            </Link>
                          )}
                          {!user.is_seller && user.seller_status !== 'pending' && (
                            <Link href="/seller/apply" className="profile-dropdown-item" onClick={() => setProfileOpen(false)}>
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6" strokeLinecap="round" strokeLinejoin="round"/></svg>
                              Become a Seller
                            </Link>
                          )}
                          {user.seller_status === 'pending' && (
                            <div className="profile-dropdown-item" style={{ color: 'var(--text-tertiary)', cursor: 'default' }}>
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                              Application Pending
                            </div>
                          )}
                          <Link href="/settings" className="profile-dropdown-item" onClick={() => setProfileOpen(false)}>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z" strokeLinecap="round" strokeLinejoin="round"/></svg>
                            Settings
                          </Link>
                          {user.is_seller && (
                            <Link href={`/seller/${user.username}`} className="profile-dropdown-item" onClick={() => setProfileOpen(false)}>
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" strokeLinecap="round" strokeLinejoin="round"/><circle cx="12" cy="7" r="4"/></svg>
                              My Profile
                            </Link>
                          )}
                          <div className="profile-dropdown-divider"></div>
                          <button className="profile-dropdown-item profile-dropdown-logout" onClick={() => { logout(); setProfileOpen(false); }}>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" strokeLinecap="round" strokeLinejoin="round"/><polyline points="16 17 21 12 16 7" strokeLinecap="round" strokeLinejoin="round"/><line x1="21" y1="12" x2="9" y2="12" strokeLinecap="round"/></svg>
                            Logout
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <div className="navbar-auth-links">
                  <Link href="/login" className="nav-quick-link">Login</Link>
                  <Link href="/register" className="nav-btn-primary">Sign Up</Link>
                </div>
              )
            )}
          </div>
        </div>
      </nav>

      {/* ── Mobile Search Bar ── */}
      <div className="mobile-search-bar" ref={mobileSearchRef}>
        <div className="container">
          <div className="mobile-search-wrapper">
            <svg className="navbar-search-icon" viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
              <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" />
            </svg>
            <input type="text" className="mobile-search-input" placeholder="Search games, categories..."
              value={searchQuery} onChange={(e) => { setSearchQuery(e.target.value); setSearchOpen(true); }}
              onFocus={() => { if (searchResults) setSearchOpen(true); }} id="mobile-search-input" />
            {searchLoading && <div className="navbar-search-spinner" style={{ right: '12px' }}></div>}
            {searchQuery && !searchLoading && (
              <button className="navbar-search-clear" onClick={clearSearch} type="button">✕</button>
            )}
            {renderSearchDropdown(true)}
          </div>
        </div>
      </div>
    </>
  );
}

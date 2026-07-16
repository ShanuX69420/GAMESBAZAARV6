'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { getUnreadCount, sendHeartbeat, searchMarketplace, getNotifications, markNotificationRead, getNotificationUnreadCount, getInboxWebSocketTicket } from '@/lib/api';
import { notificationOrderPath } from '@/lib/orderNumbers';
import { WS_BASE } from '@/lib/config';
import { buildTicketSubprotocols } from '@/lib/inbox';
import { withUnreadCount, playMessageSound, unlockMessageSound, resetMessageSoundCooldown } from '@/lib/messageAlerts';

// Badges arrive over the inbox socket; these polls are only a fallback for
// clients whose WebSocket can't connect, so they can afford to be slow.
const UNREAD_POLL_INTERVAL_MS = 60000;
const SEARCH_DEBOUNCE_MS = 300;
const NOTIF_POLL_INTERVAL_MS = 120000;
const HEARTBEAT_INTERVAL_MS = 65000;
const HEARTBEAT_MIN_SEND_GAP_MS = 60000;
const HEARTBEAT_STORAGE_KEY = 'gamesbazaar:last-heartbeat-at';
const SETUP_ALLOWED_PATHS = new Set(['/complete-profile', '/terms-of-service', '/privacy-policy']);

const NOTIF_ICONS = {
  new_order: '🛒',
  order_delivered: '📦',
  order_confirmed: '✅',
  order_disputed: '⚠️',
  order_cancelled: '❌',
  new_review: '⭐',
  item_request: '📨',
  seller_approved: '🏪',
  seller_rejected: '🚫',
};

export default function Navbar() {
  const { user, loading, logout } = useAuth();
  const [unread, setUnread] = useState(0);
  const prevUnread = useRef(0);
  const heartbeatInFlightRef = useRef(false);
  const router = useRouter();
  const pathname = usePathname();
  const setupPending = Boolean(user?.needs_setup);

  // Keep setup and its linked policies reachable while onboarding is pending.
  useEffect(() => {
    if (!loading && setupPending && !SETUP_ALLOWED_PATHS.has(pathname)) {
      router.replace('/complete-profile');
    }
  }, [setupPending, loading, pathname, router]);

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

  // ── Theme ──────────────────────────────────────────────────────────────
  // Server renders the light icon; the real value comes from <html data-theme>
  // (set pre-paint by the inline script in app/layout.js) after mount.
  const [theme, setTheme] = useState('light');
  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
  }, []);
  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    if (next === 'dark') {
      document.documentElement.dataset.theme = 'dark';
    } else {
      delete document.documentElement.dataset.theme;
    }
    try { localStorage.setItem('gb_theme', next); } catch {}
    setTheme(next);
  };

  // ── Chat unread ────────────────────────────────────────────────────────
  const fetchUnread = useCallback(() => {
    if (!user || setupPending) return;
    getUnreadCount().then(d => {
      const count = d.unread_count || 0;
      setUnread(count);
      if (count !== prevUnread.current) {
        prevUnread.current = count;
        window.dispatchEvent(new Event('chatUpdate'));
      }
    }).catch(() => {});
  }, [user, setupPending]);

  useEffect(() => {
    if (!user || setupPending) { setUnread(0); prevUnread.current = 0; return; }
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
  }, [user, setupPending, fetchUnread]);

  // Unlock audio on the first user gesture so the message ding can play
  // later, even while this tab sits in the background.
  useEffect(() => {
    if (!user || setupPending) return;
    window.addEventListener('pointerdown', unlockMessageSound);
    window.addEventListener('keydown', unlockMessageSound);
    return () => {
      window.removeEventListener('pointerdown', unlockMessageSound);
      window.removeEventListener('keydown', unlockMessageSound);
    };
  }, [user, setupPending]);

  // ── Tab title unread counter: "(4) GamesBazaar — …" ───────────────────
  useEffect(() => {
    const apply = () => {
      const wanted = withUnreadCount(document.title, unread);
      if (document.title !== wanted) document.title = wanted;
    };
    apply();
    // Next.js rewrites <title> on client-side navigation; watch the head
    // and re-apply. apply() is idempotent, so its own write settles the
    // observer instead of looping.
    const observer = new MutationObserver(apply);
    observer.observe(document.head, { childList: true, subtree: true, characterData: true });
    return () => {
      observer.disconnect();
      document.title = withUnreadCount(document.title, 0);
    };
  }, [unread]);

  // Heartbeat
  useEffect(() => {
    if (!user || setupPending) return;

    const readLastHeartbeatAt = () => {
      try {
        return Number(window.localStorage.getItem(HEARTBEAT_STORAGE_KEY)) || 0;
      } catch {
        return 0;
      }
    };

    const writeLastHeartbeatAt = (timestamp) => {
      try {
        window.localStorage.setItem(HEARTBEAT_STORAGE_KEY, String(timestamp));
      } catch {
        // Ignore storage failures; the in-tab guard still prevents overlap.
      }
    };

    const canHeartbeat = () => {
      const now = Date.now();
      return (
        now - readLastHeartbeatAt() >= HEARTBEAT_MIN_SEND_GAP_MS &&
        !heartbeatInFlightRef.current
      );
    };

    const sendActiveHeartbeat = async () => {
      if (!canHeartbeat()) return;
      heartbeatInFlightRef.current = true;
      writeLastHeartbeatAt(Date.now());
      try {
        await sendHeartbeat();
      } catch {
        // Presence will retry on the next eligible tick.
      } finally {
        heartbeatInFlightRef.current = false;
      }
    };

    const handleTick = () => {
      sendActiveHeartbeat();
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        sendActiveHeartbeat();
      }
    };

    // Send immediate heartbeat on mount
    sendActiveHeartbeat();

    let worker = null;
    let workerUrl = null;
    let fallbackInterval = null;

    if (typeof window !== 'undefined' && window.Worker) {
      try {
        const blob = new Blob([
          `let intervalId = null;
           self.onmessage = function(e) {
             if (e.data === 'start') {
               if (intervalId) clearInterval(intervalId);
               intervalId = setInterval(() => {
                 self.postMessage('tick');
               }, ${HEARTBEAT_INTERVAL_MS});
             } else if (e.data === 'stop') {
               if (intervalId) {
                 clearInterval(intervalId);
                 intervalId = null;
               }
             }
           };`
        ], { type: 'application/javascript' });
        workerUrl = URL.createObjectURL(blob);
        worker = new Worker(workerUrl);
        worker.onmessage = (e) => {
          if (e.data === 'tick') {
            handleTick();
          }
        };
        worker.postMessage('start');
      } catch (err) {
        console.error('Failed to start presence worker, falling back to interval:', err);
        fallbackInterval = setInterval(handleTick, HEARTBEAT_INTERVAL_MS);
      }
    } else {
      fallbackInterval = setInterval(handleTick, HEARTBEAT_INTERVAL_MS);
    }

    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('focus', handleVisibilityChange);

    return () => {
      if (worker) {
        worker.postMessage('stop');
        worker.terminate();
      }
      if (workerUrl) {
        URL.revokeObjectURL(workerUrl);
      }
      if (fallbackInterval) {
        clearInterval(fallbackInterval);
      }
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('focus', handleVisibilityChange);
    };
  }, [user, setupPending]);

  // ── Notification polling ───────────────────────────────────────────────
  const fetchNotifCount = useCallback(() => {
    if (!user || setupPending) return;
    getNotificationUnreadCount().then(d => {
      setNotifUnread(d.unread_count || 0);
    }).catch(() => {});
  }, [user, setupPending]);

  useEffect(() => {
    if (!user || setupPending) { setNotifUnread(0); return; }
    fetchNotifCount();
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') fetchNotifCount();
    }, NOTIF_POLL_INTERVAL_MS);
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') fetchNotifCount();
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [user, setupPending, fetchNotifCount]);

  // ── Real-time badges: per-user inbox socket ────────────────────────────
  // Pushes new notifications (bell) and conversation activity (messages
  // icon) instantly; the polls above stay as a fallback when the socket
  // is down. Survives client-side navigation since the navbar persists.
  useEffect(() => {
    if (!user || setupPending) return;
    let disposed = false;
    let ws = null;
    let reconnectTimer = null;
    let reconnectAttempts = 0;

    function scheduleReconnect() {
      if (disposed) return;
      clearTimeout(reconnectTimer);
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
      reconnectAttempts += 1;
      reconnectTimer = setTimeout(() => {
        if (!disposed) connectWs();
      }, delay);
    }

    async function connectWs() {
      let ticket;
      try {
        ({ ticket } = await getInboxWebSocketTicket());
      } catch {
        scheduleReconnect();
        return;
      }
      if (!ticket || disposed) return;

      ws = new WebSocket(`${WS_BASE}/ws/inbox/`, buildTicketSubprotocols(ticket));

      ws.onopen = () => {
        if (disposed) return;
        clearTimeout(reconnectTimer);
        // Catch up on anything missed while disconnected
        if (reconnectAttempts > 0) {
          fetchUnread();
          fetchNotifCount();
        }
        reconnectAttempts = 0;
      };

      ws.onmessage = (e) => {
        if (disposed) return;
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'notification') {
            setNotifUnread(prev => prev + 1);
            // Keep the dropdown list fresh if it has been loaded already
            setNotifications(prev => (prev.length ? [data.notification, ...prev].slice(0, 15) : prev));
          } else if (data.type === 'conversation_updated') {
            fetchUnread();
            // Ding only for other people's messages — our own sends echo
            // here too. Requiring the key keeps a stale backend (deploy
            // window) from dinging on the user's own messages. The sound
            // is cooled down per conversation, and replying counts as
            // caught up: the next message in that chat dings again.
            if ('sender_id' in data) {
              if (data.sender_id === user.id) {
                resetMessageSoundCooldown(data.conversation_id);
              } else {
                playMessageSound(data.conversation_id);
              }
            }
          }
          // presence events feed the inbox page; nothing to do here
        } catch { }
      };

      ws.onclose = () => scheduleReconnect();
      ws.onerror = () => {};
    }

    connectWs();

    return () => {
      disposed = true;
      clearTimeout(reconnectTimer);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, [user, setupPending, fetchUnread, fetchNotifCount]);

  const loadNotifications = useCallback(async () => {
    if (!user || setupPending) return;
    setNotifLoading(true);
    try {
      const data = await getNotifications({ limit: 15 });
      setNotifications(data.notifications || []);
      setNotifUnread(data.unread_count || 0);
    } catch { /* ignore */ } finally { setNotifLoading(false); }
  }, [user, setupPending]);

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
    const orderPath = notificationOrderPath(notif);
    if (orderPath) router.push(orderPath);
  }

  // ── Search logic ──────────────────────────────────────────────────────
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (setupPending) {
      setSearchQuery('');
      setSearchResults(null);
      setSearchOpen(false);
      setSearchLoading(false);
      return;
    }
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
  }, [searchQuery, setupPending]);

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
  const username = user?.username || 'User';

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
                  {item.game_icon_url ? (
                    <Image
                      src={item.game_icon_url}
                      alt=""
                      width={28}
                      height={28}
                      className="search-dropdown-item-img"
                      loading="lazy"
                    />
                  ) : '🎮'}
                </span>
                <span className="search-dropdown-item-label">{item.display_name}</span>
              </a>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <>
      <nav className="navbar">
        <div className="container navbar-inner">
          {/* ── Left: Logo ── */}
          <Link href={setupPending ? '/complete-profile' : '/'} className="navbar-logo" aria-label="GamesBazaar home">
            <img
              src="/icons/icon-96x96.png"
              alt=""
              className="navbar-logo-img"
              width="36"
              height="36"
            />
            <span className="navbar-logo-text">Games<span className="navbar-logo-accent">Bazaar</span></span>
          </Link>

          {/* ── Center: Desktop Search ── */}
          {!setupPending && (
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
          )}

          {/* ── Right: Nav actions ── */}
          <div className="navbar-actions">
            <button
              className="nav-icon-btn"
              onClick={toggleTheme}
              aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              suppressHydrationWarning
            >
              {theme === 'dark' ? (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
                  <circle cx="12" cy="12" r="5" />
                  <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" strokeLinecap="round" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
                  <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
            {/* Guest links render during the auth check too, so they are in
                the server HTML (no pop-in shift, crawlable). Returning
                logged-in users don't see them flash: the pre-paint auth hint
                hides .navbar-guest-links via CSS (see app/layout.js). */}
            {(
              user ? (
                setupPending ? (
                  <div className="navbar-auth-links">
                    <Link href="/complete-profile" className="nav-btn-primary">Complete Setup</Link>
                    <button type="button" className="nav-quick-link setup-logout-button" onClick={logout}>Logout</button>
                  </div>
                ) : (
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
                      <img src={user.avatar_url || '/avatar-default.svg'} alt={username} className="nav-avatar nav-avatar-img" />
                    </button>

                    {profileOpen && (
                      <div className="profile-dropdown">
                        <div className="profile-dropdown-header">
                          <img src={user.avatar_url || '/avatar-default.svg'} alt={username} className="profile-dropdown-avatar profile-dropdown-avatar-img" />
                          <div className="profile-dropdown-name">{username}</div>
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
                            <Link href={`/seller/${encodeURIComponent(username)}`} className="profile-dropdown-item" onClick={() => setProfileOpen(false)}>
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
                )
              ) : (
                <div className="navbar-auth-links navbar-guest-links">
                  <Link href="/login" className="nav-quick-link">Login</Link>
                  <Link href="/register" className="nav-btn-primary">Sign Up</Link>
                </div>
              )
            )}
          </div>
        </div>
      </nav>

      {/* ── Mobile Search Bar ── */}
      {!setupPending && (
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
              <button className="navbar-search-clear" onClick={clearSearch} type="button" aria-label="Clear search">✕</button>
            )}
            {renderSearchDropdown(true)}
          </div>
        </div>
      </div>
      )}
    </>
  );
}

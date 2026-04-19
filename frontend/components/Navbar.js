'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getUnreadCount, sendHeartbeat } from '@/lib/api';

const UNREAD_POLL_INTERVAL_MS = 15000;

export default function Navbar() {
  const [menuOpen, setMenuOpen] = useState(false);
  const { user, loading, logout } = useAuth();
  const [unread, setUnread] = useState(0);
  const prevUnread = useRef(0);

  const fetchUnread = useCallback(() => {
    if (!user) return;
    getUnreadCount().then(d => {
      const count = d.unread_count || 0;
      setUnread(count);
      // If count changed, notify inbox & other components
      if (count !== prevUnread.current) {
        prevUnread.current = count;
        window.dispatchEvent(new Event('chatUpdate'));
      }
    }).catch(() => {});
  }, [user]);

  useEffect(() => {
    if (!user) { setUnread(0); prevUnread.current = 0; return; }
    fetchUnread();
    // Poll as a fallback; WebSocket chatUpdate events still refresh immediately.
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') {
        fetchUnread();
      }
    }, UNREAD_POLL_INTERVAL_MS);

    // Also react to chatUpdate events (from WebSocket) for instant updates
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

  // Heartbeat — keep user online while site is open (every 60s)
  useEffect(() => {
    if (!user) return;
    sendHeartbeat();
    const hb = setInterval(() => sendHeartbeat(), 60000);
    return () => clearInterval(hb);
  }, [user]);

  return (
    <>
      <nav className="navbar">
        <div className="container navbar-inner">
          <Link href="/" className="navbar-logo">
            <div className="navbar-logo-icon">🎮</div>
            GamesBazaar
          </Link>

          <ul className="navbar-links">
            <li><Link href="/">Home</Link></li>
            {!loading && (
              user ? (
                <>
                  <li>
                    <Link href="/inbox" className="nav-messages-link">
                      Messages
                      {unread > 0 && <span className="nav-unread-badge">{unread}</span>}
                    </Link>
                  </li>
                  <li><Link href="/orders">Purchases</Link></li>
                  {user.is_seller && (
                    <>
                      <li><Link href="/sales">Sales</Link></li>
                      <li><Link href="/my-listings">My Listings</Link></li>
                    </>
                  )}
                  <li><Link href="/wallet">Wallet</Link></li>
                  <li><Link href="/dashboard">Dashboard</Link></li>
                  <li>
                    <button onClick={logout} className="nav-btn-text">
                      Logout
                    </button>
                  </li>
                  <li className="nav-user-badge">
                    <Link href={user.is_seller ? `/seller/${user.username}` : '/dashboard'}>{user.username}</Link>
                  </li>
                </>
              ) : (
                <>
                  <li><Link href="/login">Login</Link></li>
                  <li><Link href="/register" className="nav-btn-primary">Sign Up</Link></li>
                </>
              )
            )}
          </ul>

          <button
            className="navbar-hamburger"
            onClick={() => setMenuOpen(!menuOpen)}
            aria-label="Toggle menu"
          >
            <span></span>
            <span></span>
            <span></span>
          </button>
        </div>
      </nav>

      <div className={`mobile-menu ${menuOpen ? 'open' : ''}`}>
        <Link href="/" onClick={() => setMenuOpen(false)}>Home</Link>
        {!loading && (
          user ? (
            <>
              <Link href="/inbox" onClick={() => setMenuOpen(false)}>
                Messages {unread > 0 && `(${unread})`}
              </Link>
              <Link href="/orders" onClick={() => setMenuOpen(false)}>Purchases</Link>
              {user.is_seller && (
                <>
                  <Link href="/sales" onClick={() => setMenuOpen(false)}>Sales</Link>
                  <Link href="/my-listings" onClick={() => setMenuOpen(false)}>My Listings</Link>
                </>
              )}
              <Link href={user.is_seller ? `/seller/${user.username}` : '/dashboard'} onClick={() => setMenuOpen(false)}>
                My Profile
              </Link>
              <Link href="/wallet" onClick={() => setMenuOpen(false)}>Wallet</Link>
              <Link href="/dashboard" onClick={() => setMenuOpen(false)}>Dashboard</Link>
              <a href="#" onClick={(e) => { e.preventDefault(); logout(); setMenuOpen(false); }}>
                Logout ({user.username})
              </a>
            </>
          ) : (
            <>
              <Link href="/login" onClick={() => setMenuOpen(false)}>Login</Link>
              <Link href="/register" onClick={() => setMenuOpen(false)}>Sign Up</Link>
            </>
          )
        )}
      </div>
    </>
  );
}

'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getUnreadCount } from '@/lib/api';

export default function Navbar() {
  const [menuOpen, setMenuOpen] = useState(false);
  const { user, loading, logout } = useAuth();
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (!user) { setUnread(0); return; }
    const fetchUnread = () => {
      getUnreadCount().then(d => setUnread(d.unread_count || 0)).catch(() => {});
    };
    fetchUnread();
    const interval = setInterval(fetchUnread, 5000);
    return () => clearInterval(interval);
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
                      💬 Messages
                      {unread > 0 && <span className="nav-unread-badge">{unread}</span>}
                    </Link>
                  </li>
                  <li><Link href="/dashboard">Dashboard</Link></li>
                  <li>
                    <button onClick={logout} className="nav-btn-text">
                      Logout
                    </button>
                  </li>
                  <li className="nav-user-badge">{user.username}</li>
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
                💬 Messages {unread > 0 && `(${unread})`}
              </Link>
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

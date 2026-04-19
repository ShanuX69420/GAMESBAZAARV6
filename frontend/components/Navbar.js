'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { getUnreadCount, sendHeartbeat, searchMarketplace } from '@/lib/api';

const UNREAD_POLL_INTERVAL_MS = 15000;
const SEARCH_DEBOUNCE_MS = 300;

export default function Navbar() {
  const [menuOpen, setMenuOpen] = useState(false);
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

  // ── Search logic ──────────────────────────────────────────────────────
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!searchQuery || searchQuery.length < 2) {
      setSearchResults(null);
      setSearchLoading(false);
      return;
    }
    setSearchLoading(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const data = await searchMarketplace(searchQuery);
        setSearchResults(data);
        setSearchOpen(true);
      } catch {
        setSearchResults(null);
      } finally {
        setSearchLoading(false);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [searchQuery]);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClick = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target) &&
          mobileSearchRef.current && !mobileSearchRef.current.contains(e.target)) {
        setSearchOpen(false);
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
    setMenuOpen(false);
    router.push(`/games/${item.game_slug}/${item.category_slug}`);
  }

  const results = searchResults?.results || [];

  // Shared dropdown renderer
  function renderDropdown(isMobile = false) {
    if (!searchOpen || searchQuery.length < 2) return null;
    return (
      <div className={isMobile ? 'mobile-search-dropdown' : 'search-dropdown'}>
        {results.length === 0 && !searchLoading && (
          <div className="search-dropdown-empty">
            No results for &ldquo;{searchQuery}&rdquo;
          </div>
        )}
        {results.length > 0 && (
          <div className="search-dropdown-section">
            <div className="search-dropdown-section-title">Search Results</div>
            {results.map((item) => (
              <a
                key={item.id}
                href={`/games/${item.game_slug}/${item.category_slug}`}
                className="search-dropdown-item"
                onClick={(e) => handleResultClick(e, item)}
              >
                <span className="search-dropdown-item-icon">
                  {item.game_icon_url ? (
                    <img src={item.game_icon_url} alt="" className="search-dropdown-item-img" />
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
          <Link href="/" className="navbar-logo">
            <div className="navbar-logo-icon">🎮</div>
            GamesBazaar
          </Link>

          {/* ── Desktop Search Bar ─────────────────────────────────── */}
          <div className="navbar-search desktop-only" ref={searchRef}>
            <div className="navbar-search-form">
              <svg className="navbar-search-icon" viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" />
              </svg>
              <input
                type="text"
                className="navbar-search-input"
                placeholder="Search games, categories..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onFocus={() => { if (searchResults) setSearchOpen(true); }}
                id="navbar-search-input"
              />
              {searchLoading && (
                <div className="navbar-search-spinner"></div>
              )}
              {searchQuery && !searchLoading && (
                <button
                  className="navbar-search-clear"
                  onClick={clearSearch}
                  type="button"
                  aria-label="Clear search"
                >
                  ✕
                </button>
              )}
            </div>
            {renderDropdown(false)}
          </div>

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

      {/* ── Mobile Search Bar (always visible below navbar on mobile) ── */}
      <div className="mobile-search-bar" ref={mobileSearchRef}>
        <div className="container">
          <div className="mobile-search-wrapper">
            <svg className="navbar-search-icon" viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
              <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" />
            </svg>
            <input
              type="text"
              className="mobile-search-input"
              placeholder="Search games, categories..."
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setSearchOpen(true); }}
              onFocus={() => { if (searchResults) setSearchOpen(true); }}
              id="mobile-search-input"
            />
            {searchLoading && (
              <div className="navbar-search-spinner" style={{ right: '12px' }}></div>
            )}
            {searchQuery && !searchLoading && (
              <button className="navbar-search-clear" onClick={clearSearch} type="button">✕</button>
            )}
            {renderDropdown(true)}
          </div>
        </div>
      </div>

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

'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';

export default function Navbar() {
  const [menuOpen, setMenuOpen] = useState(false);
  const { user, loading, logout } = useAuth();

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

'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getSellerStatus, applyAsSeller, getMyListings, getWallet, getMySales } from '@/lib/api';

export default function DashboardPage() {
  const { user, loading, fetchUser } = useAuth();
  const router = useRouter();
  const [sellerData, setSellerData] = useState(null);
  const [listings, setListings] = useState([]);
  const [walletData, setWalletData] = useState(null);
  const [salesSummary, setSalesSummary] = useState(null);
  const [applicationNote, setApplicationNote] = useState('');
  const [applyError, setApplyError] = useState('');
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    if (!loading && !user) {
      router.push('/login');
      return;
    }
    if (user) {
      getSellerStatus().then(setSellerData).catch(() => {});
      getWallet().then(setWalletData).catch(() => {});
      getMyListings().then(setListings).catch(() => {});
      getMySales({ limit: 1, offset: 0 }).then(data => setSalesSummary(data.summary)).catch(() => {});
    }
  }, [user, loading, router]);

  async function handleApply(e) {
    e.preventDefault();
    setApplyError('');
    setApplying(true);
    try {
      await applyAsSeller(applicationNote);
      await fetchUser();
      const status = await getSellerStatus();
      setSellerData(status);
    } catch (err) {
      setApplyError(err.message);
    } finally {
      setApplying(false);
    }
  }

  if (loading || !user) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  const pendingSales = salesSummary?.pending_count ?? 0;

  return (
    <div className="container">
      <div className="page-header">
        <h1 className="page-title">Dashboard</h1>
        <p className="page-subtitle">Welcome back, <strong>{user.username}</strong></p>
      </div>

      {/* Quick Stats */}
      <div className="dashboard-stats">
        <Link href="/wallet" className="stat-card">
          <div className="stat-icon">💰</div>
          <div className="stat-info">
            <div className="stat-value">
              PKR {walletData ? Number(walletData.balance).toLocaleString('en-PK', { minimumFractionDigits: 2 }) : '0.00'}
            </div>
            <div className="stat-label">Wallet Balance</div>
          </div>
        </Link>
        <Link href="/orders" className="stat-card">
          <div className="stat-icon">🛍️</div>
          <div className="stat-info">
            <div className="stat-value">My Purchases</div>
            <div className="stat-label">View your order history</div>
          </div>
        </Link>
        {sellerData?.is_seller && (
          <>
            <Link href="/sales" className="stat-card">
              <div className="stat-icon">📦</div>
              <div className="stat-info">
                <div className="stat-value">{pendingSales} pending</div>
                <div className="stat-label">Sales to Deliver</div>
              </div>
            </Link>
            <Link href="/my-listings" className="stat-card">
              <div className="stat-icon">🛒</div>
              <div className="stat-info">
                <div className="stat-value">{listings.length}</div>
                <div className="stat-label">My Listings</div>
              </div>
            </Link>
          </>
        )}
      </div>

      {/* Seller Status Section */}
      <section className="section">
        <div className="dashboard-card">
          <h2 className="card-title">🏪 Seller Status</h2>
          {!sellerData ? (
            <div className="loading"><div className="loading-spinner"></div> Loading...</div>
          ) : sellerData.seller_status === 'none' ? (
            <div>
              <p style={{ marginBottom: '16px', color: 'var(--text-secondary)' }}>
                Want to sell on GamesBazaar? Apply to become a seller.
              </p>
              {applyError && <div className="alert alert-error">{applyError}</div>}
              <form onSubmit={handleApply}>
                <div className="form-group">
                  <label className="form-label">Tell us about yourself</label>
                  <textarea
                    className="form-textarea"
                    value={applicationNote}
                    onChange={(e) => setApplicationNote(e.target.value)}
                    placeholder="What do you plan to sell? Any experience?"
                    rows={3}
                    required
                  />
                </div>
                <button type="submit" className="btn btn-primary" disabled={applying}>
                  {applying ? 'Submitting...' : 'Apply as Seller'}
                </button>
              </form>
            </div>
          ) : sellerData.seller_status === 'pending' ? (
            <div>
              <div className="status-badge status-pending">
                ⏳ Your seller application is under review
              </div>
            </div>
          ) : sellerData.seller_status === 'approved' ? (
            <div>
              <div className="status-badge status-approved">
                ✅ You are an approved seller
              </div>
              <div style={{ marginTop: '16px', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                <Link href="/dashboard/create-listing" className="btn btn-primary">
                  + Create New Listing
                </Link>
                <Link href="/my-listings" className="btn btn-outline">
                  📋 View My Listings
                </Link>
                <Link href="/sales" className="btn btn-outline">
                  💼 View My Sales
                </Link>
              </div>
            </div>
          ) : (
            <div className="status-badge status-rejected">
              ❌ Your seller application was rejected
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

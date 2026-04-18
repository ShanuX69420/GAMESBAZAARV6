'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getSellerStatus, applyAsSeller, getMyListings } from '@/lib/api';

export default function DashboardPage() {
  const { user, loading, fetchUser } = useAuth();
  const router = useRouter();
  const [sellerData, setSellerData] = useState(null);
  const [listings, setListings] = useState([]);
  const [applicationNote, setApplicationNote] = useState('');
  const [applyError, setApplyError] = useState('');
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    if (!loading && !user) {
      router.push('/login');
    }
  }, [user, loading, router]);

  useEffect(() => {
    if (user) {
      getSellerStatus().then(setSellerData).catch(() => {});
      getMyListings().then(setListings).catch(() => {});
    }
  }, [user]);

  async function handleApply(e) {
    e.preventDefault();
    setApplyError('');
    setApplying(true);
    try {
      await applyAsSeller(applicationNote);
      const status = await getSellerStatus();
      setSellerData(status);
      await fetchUser();
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

  return (
    <div className="container">
      <div className="page-header">
        <h1 className="page-title">Dashboard</h1>
        <p className="page-subtitle">Welcome back, <strong>{user.username}</strong></p>
      </div>

      {/* Seller Status Section */}
      <section className="section">
        <div className="dashboard-card">
          <h2 className="card-title">🏪 Seller Status</h2>

          {!sellerData || sellerData.seller_status === 'none' ? (
            <div>
              <p className="card-text">
                Want to sell on GamesBazaar? Apply to become a seller!
              </p>
              {applyError && <div className="alert alert-error">{applyError}</div>}
              <form onSubmit={handleApply} className="seller-apply-form">
                <div className="form-group">
                  <label className="form-label">Why do you want to sell?</label>
                  <textarea
                    className="form-textarea"
                    value={applicationNote}
                    onChange={(e) => setApplicationNote(e.target.value)}
                    placeholder="Tell us about yourself and what you plan to sell..."
                    rows={3}
                    required
                  />
                </div>
                <button type="submit" className="btn btn-primary" disabled={applying}>
                  {applying ? 'Submitting...' : 'Apply to Sell'}
                </button>
              </form>
            </div>
          ) : sellerData.seller_status === 'pending' ? (
            <div className="status-badge status-pending">
              ⏳ Your seller application is under review
            </div>
          ) : sellerData.seller_status === 'approved' ? (
            <div>
              <div className="status-badge status-approved">
                ✅ You are an approved seller
              </div>
              <div style={{ marginTop: '16px' }}>
                <Link href="/dashboard/create-listing" className="btn btn-primary">
                  + Create New Listing
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

      {/* My Listings Section */}
      {sellerData?.is_seller && (
        <section className="section">
          <div className="section-header">
            <h2 className="section-title">My Listings</h2>
            <Link href="/dashboard/create-listing" className="btn btn-sm btn-primary">
              + New Listing
            </Link>
          </div>

          {listings.length > 0 ? (
            <div className="listings-table-wrap">
              <table className="listings-table">
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Game</th>
                    <th>Category</th>
                    <th>Price</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {listings.map((listing) => (
                    <tr key={listing.id}>
                      <td>
                        <Link href={`/listing/${listing.id}`} className="listing-link">
                          {listing.title}
                        </Link>
                      </td>
                      <td>{listing.game_name}</td>
                      <td>{listing.category_name}</td>
                      <td className="listing-price">PKR {listing.price}</td>
                      <td>
                        <span className={`status-pill status-${listing.status}`}>
                          {listing.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">📦</div>
              <p>No listings yet. Create your first listing!</p>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

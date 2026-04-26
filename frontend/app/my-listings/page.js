'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getMyListings, updateListing, deleteListing } from '@/lib/api';

const MY_LISTING_PAGE_SIZE = 48;

export default function MyListingsPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [listings, setListings] = useState([]);
  const [listingPagination, setListingPagination] = useState(null);
  const [listingSummary, setListingSummary] = useState(null);
  const [loadingListings, setLoadingListings] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [actionLoading, setActionLoading] = useState(null);
  const [editModal, setEditModal] = useState(null);
  const [editForm, setEditForm] = useState({ title: '', description: '', price: '', quantity: '', status: '' });
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    if (!loading && !user) router.push('/login');
    if (!loading && user && !user.is_seller) router.push('/dashboard');
  }, [user, loading, router]);

  useEffect(() => {
    if (user && user.is_seller) loadListings();
  }, [user]);

  async function loadListings(offset = 0, append = false) {
    if (append) {
      setLoadingMore(true);
    } else {
      setLoadingListings(true);
    }
    try {
      const data = await getMyListings({
        limit: MY_LISTING_PAGE_SIZE,
        offset,
      });
      const nextListings = data.listings || [];
      setListings(prev => append ? [...prev, ...nextListings] : nextListings);
      setListingPagination(data.pagination || null);
      setListingSummary(data.summary || null);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingListings(false);
      setLoadingMore(false);
    }
  }

  function openEditModal(listing) {
    setEditForm({
      title: listing.title,
      description: listing.description || '',
      price: listing.price,
      quantity: listing.quantity ?? '',
      status: listing.status,
    });
    setEditModal(listing.id);
  }

  async function handleEditSave() {
    setActionLoading(editModal);
    setError('');
    setSuccess('');
    try {
      const data = {
        title: editForm.title,
        description: editForm.description,
        price: parseFloat(editForm.price),
        quantity: editForm.quantity === '' || editForm.quantity === null ? null : parseInt(editForm.quantity),
        status: editForm.status,
      };
      await updateListing(editModal, data);
      setSuccess('Listing updated successfully!');
      setEditModal(null);
      await loadListings();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading(null);
    }
  }

  async function handleDelete(listingId) {
    if (!window.confirm('Are you sure you want to delete this listing? This cannot be undone.')) return;
    setActionLoading(listingId);
    setError('');
    setSuccess('');
    try {
      await deleteListing(listingId);
      setSuccess('Listing deleted.');
      await loadListings();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading(null);
    }
  }

  if (loading || !user) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  if (!user.is_seller) return null;

  const activeCount = listingSummary?.active_count ?? listings.filter(l => l.status === 'active').length;
  const soldCount = listingSummary?.sold_count ?? listings.filter(l => l.status === 'sold').length;
  const totalCount = listingSummary?.total_count ?? listingPagination?.count ?? listings.length;

  return (
    <div className="container">
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h1 className="page-title">🛒 My Listings</h1>
            <p className="page-subtitle">Manage your marketplace listings</p>
          </div>
          <Link href="/dashboard/create-listing" className="btn btn-primary">
            + Create New Listing
          </Link>
        </div>
      </div>

      {/* Listings Stats */}
      <div className="dashboard-stats">
        <div className="stat-card">
          <div className="stat-icon">🟢</div>
          <div className="stat-info">
            <div className="stat-value">{activeCount}</div>
            <div className="stat-label">Active Listings</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon">📦</div>
          <div className="stat-info">
            <div className="stat-value">{totalCount}</div>
            <div className="stat-label">Total Listings</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon">🏷️</div>
          <div className="stat-info">
            <div className="stat-value">{soldCount}</div>
            <div className="stat-label">Sold Out</div>
          </div>
        </div>
      </div>

      {success && <div className="alert alert-success">{success}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {loadingListings ? (
        <div className="loading"><div className="loading-spinner"></div> Loading listings...</div>
      ) : listings.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📦</div>
          <p>No listings yet. Create your first listing to start selling!</p>
          <Link href="/dashboard/create-listing" className="btn btn-primary" style={{ marginTop: '12px' }}>
            + Create New Listing
          </Link>
        </div>
      ) : (
        <>
        <div className="listings-table-wrap">
          <table className="listings-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Game</th>
                <th>Category</th>
                <th>Price</th>
                <th>Stock</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {listings.map((listing) => (
                <tr key={listing.id}>
                  <td>
                    <Link href={`/listing/${listing.id}`} className="listing-link">
                      {listing.is_auto_delivery && (
                        <svg className="instant-delivery-icon" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" style={{ marginRight: '4px', verticalAlign: '-2px' }}>
                          <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z"/>
                        </svg>
                      )}
                      {listing.title}
                    </Link>
                  </td>
                  <td>{listing.game_name}</td>
                  <td>{listing.category_name}</td>
                  <td className="listing-price">PKR {listing.price}</td>
                  <td>{listing.quantity === null ? '∞' : listing.quantity}</td>
                  <td>
                    <span className={`status-pill status-${listing.status}`}>
                      {listing.status}
                    </span>
                  </td>
                  <td>
                    <div className="listing-actions">
                      <button
                        className="btn btn-outline btn-xs"
                        onClick={() => openEditModal(listing)}
                      >
                        ✏️ Edit
                      </button>
                      <button
                        className="btn btn-outline btn-xs btn-danger"
                        onClick={() => handleDelete(listing.id)}
                        disabled={actionLoading === listing.id}
                      >
                        🗑️ Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {listingPagination?.next_offset !== null && listingPagination?.next_offset !== undefined && (
          <button
            className="btn btn-outline btn-full"
            style={{ marginTop: '16px' }}
            onClick={() => loadListings(listingPagination.next_offset, true)}
            disabled={loadingMore}
          >
            {loadingMore ? 'Loading...' : 'Load More'}
          </button>
        )}
        </>
      )}

      {/* Edit Listing Modal */}
      {editModal && (
        <div className="image-preview-overlay" onClick={() => setEditModal(null)}>
          <div className="image-preview-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '520px' }}>
            <div className="image-preview-header">
              <span>Edit Listing</span>
              <button className="image-preview-close" onClick={() => setEditModal(null)}>✕</button>
            </div>
            <div style={{ padding: '20px' }}>
              <div className="form-group">
                <label className="form-label">Title</label>
                <input
                  type="text"
                  className="form-input"
                  value={editForm.title}
                  onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}
                  required
                />
              </div>
              <div className="form-group">
                <label className="form-label">Description</label>
                <textarea
                  className="form-textarea"
                  value={editForm.description}
                  onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                  rows={3}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Price (PKR)</label>
                <input
                  type="number"
                  className="form-input"
                  value={editForm.price}
                  onChange={(e) => setEditForm({ ...editForm, price: e.target.value })}
                  min="1"
                  step="1"
                  required
                />
              </div>
              <div className="form-group">
                <label className="form-label">Stock</label>
                <input
                  type="number"
                  className="form-input"
                  value={editForm.quantity}
                  onChange={(e) => setEditForm({ ...editForm, quantity: e.target.value })}
                  min="1"
                  placeholder="Leave empty for unlimited"
                />
                <span className="form-hint">Leave empty for evergreen (unlimited) listing</span>
              </div>
              <div className="form-group">
                <label className="form-label">Status</label>
                <select
                  className="form-input"
                  value={editForm.status}
                  onChange={(e) => setEditForm({ ...editForm, status: e.target.value })}
                >
                  <option value="active">Active</option>
                  <option value="inactive">Inactive</option>
                  <option value="sold">Sold</option>
                </select>
              </div>
              <div style={{ display: 'flex', gap: '10px', marginTop: '16px', justifyContent: 'flex-end' }}>
                <button className="btn btn-outline" onClick={() => setEditModal(null)}>Cancel</button>
                <button
                  className="btn btn-primary"
                  onClick={handleEditSave}
                  disabled={actionLoading}
                >
                  {actionLoading ? 'Saving...' : '💾 Save Changes'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

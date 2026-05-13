'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getMyListings, updateListing, deleteListing, restockAutoDeliveryListing, getAutoDeliveryStock, getAutoDeliveryStockItem, updateAutoDeliveryStock, removeAutoDeliveryStock } from '@/lib/api';

const MY_LISTING_PAGE_SIZE = 24;

const STATUS_TABS = [
  { key: '', label: 'All Listings', icon: '📋' },
  { key: 'active', label: 'Active', icon: '🟢' },
  { key: 'inactive', label: 'Inactive', icon: '⏸️' },
  { key: 'sold', label: 'Sold Out', icon: '🏷️' },
];

export default function MyListingsPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [listings, setListings] = useState([]);
  const [listingPagination, setListingPagination] = useState(null);
  const [listingSummary, setListingSummary] = useState(null);
  const [statusCounts, setStatusCounts] = useState({});
  const [sellerGames, setSellerGames] = useState([]);
  const [loadingListings, setLoadingListings] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [actionLoading, setActionLoading] = useState(null);
  const [editModal, setEditModal] = useState(null);
  const [editForm, setEditForm] = useState({ title: '', description: '', price: '', quantity: '', status: '' });
  const [restockModal, setRestockModal] = useState(null);
  const [restockData, setRestockData] = useState('');
  const [stockModal, setStockModal] = useState(null);
  const [stockItems, setStockItems] = useState([]);
  const [stockLoading, setStockLoading] = useState(false);
  const [selectedStockItems, setSelectedStockItems] = useState(new Set());
  const [stockListingTitle, setStockListingTitle] = useState('');
  const [editItem, setEditItem] = useState(null);
  const [editItemContent, setEditItemContent] = useState('');
  const [editItemLoading, setEditItemLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Filter state
  const [statusFilter, setStatusFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [gameFilter, setGameFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const latestRequestId = useRef(0);

  useEffect(() => {
    if (!loading && !user) router.push('/login');
    if (!loading && user && !user.is_seller) router.push('/dashboard');
  }, [user, loading, router]);

  const loadListings = useCallback(async ({ append = false, offset = 0 } = {}) => {
    const requestId = ++latestRequestId.current;
    if (append) {
      setLoadingMore(true);
    } else {
      setLoadingListings(true);
    }
    try {
      const data = await getMyListings({
        limit: MY_LISTING_PAGE_SIZE,
        offset,
        status: statusFilter || undefined,
        search: debouncedSearch || undefined,
        game: gameFilter || undefined,
        category: categoryFilter || undefined,
        includeFacets: !append,
      });
      if (requestId !== latestRequestId.current) return;
      const nextListings = data.listings || [];
      setListings(prev => append ? [...prev, ...nextListings] : nextListings);
      setListingPagination(data.pagination || null);
      if (data.summary) setListingSummary(data.summary);
      if (data.status_counts) setStatusCounts(data.status_counts);
      if (data.seller_games) setSellerGames(data.seller_games);
    } catch (err) {
      if (requestId === latestRequestId.current) console.error(err);
    } finally {
      if (requestId === latestRequestId.current) {
        setLoadingListings(false);
        setLoadingMore(false);
      }
    }
  }, [statusFilter, debouncedSearch, gameFilter, categoryFilter]);

  useEffect(() => {
    if (user && user.is_seller) loadListings();
  }, [user, loadListings]);

  // Debounce search
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      setDebouncedSearch(searchQuery.trim());
    }, 300);
    return () => clearTimeout(timeoutId);
  }, [searchQuery]);

  // When game changes, clear category filter (it may no longer be relevant)
  function handleGameChange(slug) {
    setGameFilter(slug);
    setCategoryFilter('');
  }

  function clearFilters() {
    setStatusFilter('');
    setSearchQuery('');
    setDebouncedSearch('');
    setGameFilter('');
    setCategoryFilter('');
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

  function openRestockModal(listing) {
    setRestockModal(listing.id);
    setRestockData('');
    setError('');
    setSuccess('');
  }

  async function handleRestockSave() {
    const lines = restockData.split('\n').filter(line => line.trim());
    if (lines.length === 0) {
      setError('Add at least one delivery item.');
      return;
    }

    setActionLoading(restockModal);
    setError('');
    setSuccess('');
    try {
      await restockAutoDeliveryListing(restockModal, {
        auto_delivery_data: restockData,
        activate: true,
      });
      setSuccess(`Added ${lines.length} item${lines.length === 1 ? '' : 's'} to the listing.`);
      setRestockModal(null);
      setRestockData('');
      await loadListings();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading(null);
    }
  }

  async function openStockModal(listing) {
    setStockModal(listing.id);
    setStockListingTitle(listing.title);
    setStockItems([]);
    setSelectedStockItems(new Set());
    setStockLoading(true);
    setError('');
    setSuccess('');
    try {
      const data = await getAutoDeliveryStock(listing.id);
      setStockItems(data.items || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setStockLoading(false);
    }
  }

  function toggleStockItem(index) {
    setSelectedStockItems(prev => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }

  function toggleAllStockItems() {
    if (selectedStockItems.size === stockItems.length) {
      setSelectedStockItems(new Set());
    } else {
      setSelectedStockItems(new Set(stockItems.map(item => item.index)));
    }
  }

  async function handleRemoveStockItems() {
    if (selectedStockItems.size === 0) return;
    if (selectedStockItems.size === stockItems.length) {
      setError('Cannot remove all items. Delete the listing instead, or leave at least one item.');
      return;
    }
    const count = selectedStockItems.size;
    if (!window.confirm(`Remove ${count} item${count !== 1 ? 's' : ''} from stock? This cannot be undone.`)) return;

    setActionLoading('stock-remove');
    setError('');
    setSuccess('');
    try {
      const result = await removeAutoDeliveryStock(stockModal, Array.from(selectedStockItems));
      setSuccess(result.message);
      setSelectedStockItems(new Set());
      // Reload stock
      const data = await getAutoDeliveryStock(stockModal);
      setStockItems(data.items || []);
      await loadListings();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading(null);
    }
  }

  async function openEditItem(itemIndex) {
    setEditItem(itemIndex);
    setEditItemContent('');
    setEditItemLoading(true);
    setError('');
    try {
      const data = await getAutoDeliveryStockItem(stockModal, itemIndex);
      setEditItemContent(data.content);
    } catch (err) {
      setError(err.message);
      setEditItem(null);
    } finally {
      setEditItemLoading(false);
    }
  }

  async function handleEditItemSave() {
    if (!editItemContent.trim()) {
      setError('Item content cannot be empty.');
      return;
    }
    setActionLoading('stock-edit');
    setError('');
    setSuccess('');
    try {
      await updateAutoDeliveryStock(stockModal, [{ index: editItem, content: editItemContent }]);
      setSuccess(`Item #${editItem + 1} updated successfully.`);
      setEditItem(null);
      setEditItemContent('');
      // Reload stock list
      const data = await getAutoDeliveryStock(stockModal);
      setStockItems(data.items || []);
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

  async function handleQuickToggle(listing) {
    const newStatus = listing.status === 'active' ? 'inactive' : 'active';
    setActionLoading(listing.id);
    setError('');
    try {
      await updateListing(listing.id, { status: newStatus });
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

  const activeCount = listingSummary?.active_count ?? 0;
  const soldCount = listingSummary?.sold_count ?? 0;
  const totalCount = listingSummary?.total_count ?? 0;
  const hasActiveFilters = statusFilter || searchQuery || gameFilter || categoryFilter;

  // Get categories for the currently selected game
  const selectedGame = sellerGames.find(g => g.slug === gameFilter);
  const availableCategories = selectedGame?.categories || [];

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

      {/* Filter Toolbar */}
      <div className="orders-filter-toolbar">
        {/* Status Tabs */}
        <div className="orders-status-tabs">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.key}
              className={`orders-status-tab ${statusFilter === tab.key ? 'active' : ''}`}
              onClick={() => setStatusFilter(tab.key)}
            >
              <span className="orders-tab-icon">{tab.icon}</span>
              <span className="orders-tab-label">{tab.label}</span>
              {tab.key && statusCounts[tab.key] > 0 && (
                <span className="orders-tab-count">{statusCounts[tab.key]}</span>
              )}
            </button>
          ))}
        </div>

        {/* Search + Game/Category Filters */}
        <div className="orders-filter-row">
          <div className="orders-search-wrap">
            <span className="orders-search-icon">🔍</span>
            <input
              type="text"
              className="orders-search-input"
              placeholder="Search listings by title..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button
                className="orders-search-clear"
                onClick={() => {
                  setSearchQuery('');
                  setDebouncedSearch('');
                }}
              >✕</button>
            )}
          </div>

          {/* Game Filter */}
          {sellerGames.length > 0 && (
            <select
              className="ml-filter-select"
              value={gameFilter}
              onChange={(e) => handleGameChange(e.target.value)}
            >
              <option value="">All Games</option>
              {sellerGames.map((g) => (
                <option key={g.slug} value={g.slug}>
                  {g.name} ({g.listing_count})
                </option>
              ))}
            </select>
          )}

          {/* Category Filter — only shown when a game is selected */}
          {gameFilter && availableCategories.length > 0 && (
            <select
              className="ml-filter-select"
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
            >
              <option value="">All Categories</option>
              {availableCategories.map((c) => (
                <option key={c.slug} value={c.slug}>
                  {c.icon} {c.name} ({c.listing_count})
                </option>
              ))}
            </select>
          )}

          {hasActiveFilters && (
            <button className="orders-clear-filters" onClick={clearFilters}>
              ✕ Clear All
            </button>
          )}
        </div>

        {/* Active filter tags */}
        {(gameFilter || categoryFilter) && (
          <div className="ml-active-filters">
            {gameFilter && (
              <span className="ml-filter-tag">
                🎮 {sellerGames.find(g => g.slug === gameFilter)?.name || gameFilter}
                <button className="ml-filter-tag-remove" onClick={() => handleGameChange('')}>✕</button>
              </span>
            )}
            {categoryFilter && (
              <span className="ml-filter-tag">
                📁 {availableCategories.find(c => c.slug === categoryFilter)?.name || categoryFilter}
                <button className="ml-filter-tag-remove" onClick={() => setCategoryFilter('')}>✕</button>
              </span>
            )}
          </div>
        )}
      </div>

      {success && <div className="alert alert-success">{success}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {loadingListings ? (
        <div className="loading"><div className="loading-spinner"></div> Loading listings...</div>
      ) : listings.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📦</div>
          <p>{hasActiveFilters ? 'No listings match your filters.' : 'No listings yet. Create your first listing to start selling!'}</p>
          {hasActiveFilters ? (
            <button className="btn btn-outline btn-sm" onClick={clearFilters} style={{ marginTop: 12 }}>
              Clear Filters
            </button>
          ) : (
            <Link href="/dashboard/create-listing" className="btn btn-primary" style={{ marginTop: '12px' }}>
              + Create New Listing
            </Link>
          )}
        </div>
      ) : (
        <>
          {/* Results count */}
          <div className="ml-results-bar">
            <span className="ml-results-count">
              Showing {listings.length} of {listingPagination?.count ?? listings.length} listing{(listingPagination?.count ?? listings.length) !== 1 ? 's' : ''}
            </span>
          </div>

          <div className="ml-cards-grid">
            {listings.map((listing) => (
              <div key={listing.id} className={`ml-card ml-card-${listing.status}`}>
                <div className="ml-card-header">
                  <div className="ml-card-title-row">
                    <Link href={`/listing/${listing.id}`} className="ml-card-title">
                      {listing.is_auto_delivery && (
                        <svg className="instant-delivery-icon" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" style={{ marginRight: '4px', verticalAlign: '-2px' }}>
                          <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z"/>
                        </svg>
                      )}
                      {listing.title}
                    </Link>
                    <span className={`status-pill status-${listing.status}`}>
                      {listing.status}
                    </span>
                  </div>
                  <div className="ml-card-price">PKR {listing.price}</div>
                </div>

                <div className="ml-card-meta">
                  <span className="ml-card-meta-item">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="7" width="20" height="15" rx="2" ry="2"/><polyline points="17 2 12 7 7 2"/></svg>
                    {listing.game_name}
                  </span>
                  <span className="ml-card-meta-item">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></svg>
                    {listing.category_name}
                  </span>
                  <span className="ml-card-meta-item">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 16V8a2 2 0 00-1-1.73L13 2.27a2 2 0 00-2 0L4 6.27A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/></svg>
                    Stock: {listing.quantity === null ? '∞' : listing.quantity}
                  </span>
                </div>

                <div className="ml-card-actions">
                  {listing.status !== 'sold' && (
                    <button
                      className={`ml-toggle-btn ${listing.status === 'active' ? 'ml-toggle-deactivate' : 'ml-toggle-activate'}`}
                      onClick={() => handleQuickToggle(listing)}
                      disabled={actionLoading === listing.id}
                      title={listing.status === 'active' ? 'Deactivate listing' : 'Activate listing'}
                    >
                      {actionLoading === listing.id ? (
                        <span className="ml-btn-spinner"></span>
                      ) : listing.status === 'active' ? (
                        <>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
                          Pause
                        </>
                      ) : (
                        <>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                          Activate
                        </>
                      )}
                    </button>
                  )}
                  {listing.is_auto_delivery && (
                    <>
                      <button
                        className="ml-action-btn ml-action-stock"
                        onClick={() => openStockModal(listing)}
                        disabled={actionLoading === listing.id}
                        title="View and manage automated delivery stock"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 16V8a2 2 0 00-1-1.73L13 2.27a2 2 0 00-2 0L4 6.27A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>
                        Manage Stock
                      </button>
                      <button
                        className="ml-action-btn"
                        onClick={() => openRestockModal(listing)}
                        disabled={actionLoading === listing.id}
                        title="Add automated delivery stock"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>
                        Restock
                      </button>
                    </>
                  )}
                  <button
                    className="ml-action-btn"
                    onClick={() => openEditModal(listing)}
                    title="Edit listing"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    Edit
                  </button>
                  <button
                    className="ml-action-btn ml-action-danger"
                    onClick={() => handleDelete(listing.id)}
                    disabled={actionLoading === listing.id}
                    title="Delete listing"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>

          {listingPagination?.next_offset !== null && listingPagination?.next_offset !== undefined && (
            <button
              className="btn btn-outline btn-full"
              style={{ marginTop: '16px' }}
              onClick={() => loadListings({ append: true, offset: listingPagination.next_offset })}
              disabled={loadingMore}
            >
              {loadingMore ? 'Loading...' : 'Load More Listings'}
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

      {restockModal && (
        <div className="image-preview-overlay" onClick={() => setRestockModal(null)}>
          <div className="image-preview-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '560px' }}>
            <div className="image-preview-header">
              <span>Restock Auto Delivery</span>
              <button className="image-preview-close" onClick={() => setRestockModal(null)}>x</button>
            </div>
            <div style={{ padding: '20px' }}>
              <div className="form-group">
                <label className="form-label">Delivery items</label>
                <textarea
                  className="form-textarea"
                  value={restockData}
                  onChange={(e) => setRestockData(e.target.value)}
                  rows={8}
                  placeholder="One code, account, or key per line"
                />
                <span className="form-hint">
                  {restockData.trim()
                    ? `${restockData.split('\n').filter(line => line.trim()).length} item${restockData.split('\n').filter(line => line.trim()).length === 1 ? '' : 's'} ready to add`
                    : 'Each non-empty line becomes one item in stock.'}
                </span>
              </div>
              <div style={{ display: 'flex', gap: '10px', marginTop: '16px', justifyContent: 'flex-end' }}>
                <button className="btn btn-outline" onClick={() => setRestockModal(null)}>Cancel</button>
                <button
                  className="btn btn-primary"
                  onClick={handleRestockSave}
                  disabled={actionLoading === restockModal}
                >
                  {actionLoading === restockModal ? 'Adding...' : 'Add Stock'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Manage Stock Modal */}
      {stockModal && (
        <div className="image-preview-overlay" onClick={() => { setStockModal(null); setError(''); setSuccess(''); }}>
          <div className="stock-modal" onClick={(e) => e.stopPropagation()}>
            <div className="stock-modal-header">
              <div className="stock-modal-header-left">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 16V8a2 2 0 00-1-1.73L13 2.27a2 2 0 00-2 0L4 6.27A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/>
                  <polyline points="3.27 6.96 12 12.01 20.73 6.96"/>
                  <line x1="12" y1="22.08" x2="12" y2="12"/>
                </svg>
                <div>
                  <h3>Manage Stock</h3>
                  <p className="stock-modal-subtitle">{stockListingTitle}</p>
                </div>
              </div>
              <button className="image-preview-close" onClick={() => { setStockModal(null); setError(''); setSuccess(''); }}>✕</button>
            </div>

            <div className="stock-modal-body">
              {error && <div className="alert alert-error" style={{ margin: '0 0 12px' }}>{error}</div>}
              {success && <div className="alert alert-success" style={{ margin: '0 0 12px' }}>{success}</div>}

              {stockLoading ? (
                <div className="stock-modal-loading">
                  <div className="loading-spinner"></div>
                  <p>Loading stock items...</p>
                </div>
              ) : stockItems.length === 0 ? (
                <div className="stock-modal-empty">
                  <div className="stock-modal-empty-icon">📦</div>
                  <p>No items in stock.</p>
                  <button className="btn btn-primary btn-sm" onClick={() => { setStockModal(null); openRestockModal({ id: stockModal }); }}>
                    + Add Stock
                  </button>
                </div>
              ) : (
                <>
                  {/* Toolbar */}
                  <div className="stock-toolbar">
                    <div className="stock-toolbar-left">
                      <label className="stock-select-all">
                        <input
                          type="checkbox"
                          checked={selectedStockItems.size === stockItems.length && stockItems.length > 0}
                          onChange={toggleAllStockItems}
                          className="stock-checkbox"
                        />
                        <span>{selectedStockItems.size > 0 ? `${selectedStockItems.size} selected` : 'Select all'}</span>
                      </label>
                      <span className="stock-count-badge">{stockItems.length} item{stockItems.length !== 1 ? 's' : ''} total</span>
                    </div>
                    <div className="stock-toolbar-right">
                      {selectedStockItems.size > 0 && (
                        <button
                          className="btn btn-sm stock-remove-btn"
                          onClick={handleRemoveStockItems}
                          disabled={actionLoading === 'stock-remove'}
                        >
                          {actionLoading === 'stock-remove' ? (
                            <><div className="loading-spinner" style={{ width: '14px', height: '14px', borderWidth: '2px' }}></div> Removing...</>
                          ) : (
                            <>
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <polyline points="3 6 5 6 21 6"/>
                                <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
                              </svg>
                              Remove {selectedStockItems.size} item{selectedStockItems.size !== 1 ? 's' : ''}
                            </>
                          )}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Stock Items List */}
                  <div className="stock-items-list">
                    {stockItems.map((item) => (
                      <div
                        key={item.index}
                        className={`stock-item ${selectedStockItems.has(item.index) ? 'stock-item-selected' : ''}`}
                        onClick={() => toggleStockItem(item.index)}
                      >
                        <input
                          type="checkbox"
                          checked={selectedStockItems.has(item.index)}
                          onChange={() => toggleStockItem(item.index)}
                          className="stock-checkbox"
                          onClick={(e) => e.stopPropagation()}
                        />
                        <span className="stock-item-index">#{item.index + 1}</span>
                        <code className="stock-item-preview">{item.preview}</code>
                        <span className="stock-item-length">{item.length} chars</span>
                        <button
                          className="stock-item-edit-btn"
                          title="View & Edit"
                          onClick={(e) => { e.stopPropagation(); openEditItem(item.index); }}
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
                            <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
                          </svg>
                        </button>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>

            <div className="stock-modal-footer">
              <button
                className="btn btn-outline btn-sm"
                onClick={() => { setStockModal(null); openRestockModal({ id: stockModal }); }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>
                Add More Stock
              </button>
              <button className="btn btn-outline btn-sm" onClick={() => { setStockModal(null); setError(''); setSuccess(''); }}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Stock Item Modal */}
      {editItem !== null && (
        <div className="image-preview-overlay" style={{ zIndex: 1001 }} onClick={() => { setEditItem(null); setEditItemContent(''); }}>
          <div className="stock-edit-modal" onClick={(e) => e.stopPropagation()}>
            <div className="stock-edit-header">
              <div className="stock-edit-header-left">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
                  <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
                <span>Item #{editItem + 1}</span>
              </div>
              <button className="image-preview-close" onClick={() => { setEditItem(null); setEditItemContent(''); }}>✕</button>
            </div>
            <div className="stock-edit-body">
              {editItemLoading ? (
                <div className="stock-modal-loading">
                  <div className="loading-spinner"></div>
                  <p>Loading item content...</p>
                </div>
              ) : (
                <>
                  <label className="form-label">Item Content</label>
                  <textarea
                    className="stock-edit-textarea"
                    value={editItemContent}
                    onChange={(e) => setEditItemContent(e.target.value)}
                    rows={6}
                    placeholder="Item content (code, account, key, etc.)"
                    spellCheck={false}
                    autoFocus
                  />
                  <span className="form-hint">{editItemContent.length} characters</span>
                </>
              )}
            </div>
            <div className="stock-edit-footer">
              <button className="btn btn-outline btn-sm" onClick={() => { setEditItem(null); setEditItemContent(''); }}>
                Cancel
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={handleEditItemSave}
                disabled={actionLoading === 'stock-edit' || editItemLoading}
              >
                {actionLoading === 'stock-edit' ? 'Saving...' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

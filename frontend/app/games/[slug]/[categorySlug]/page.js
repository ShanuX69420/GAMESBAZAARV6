'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { API_BASE } from '@/lib/config';
import {
  buildGameCategoryListingUrl,
  buildSellerListingsPath,
  buildSellerProfilePath,
} from '@/lib/marketplaceUrls';

const LISTING_PAGE_SIZE = 48;

export default function GameCategoryPage() {
  const params = useParams();
  const router = useRouter();
  const { slug, categorySlug } = params;
  const searchParams = useSearchParams();
  const sellerFilter = searchParams.get('seller') || '';
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [activeFilters, setActiveFilters] = useState({});
  const [instantDeliveryFilter, setInstantDeliveryFilter] = useState(false);
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const fetchData = useCallback(async (filters = {}, offset = 0, append = false, instantOnly = false, search = '') => {
    if (append) {
      setLoadingMore(true);
    } else {
      setLoading(true);
    }
    try {
      const url = buildGameCategoryListingUrl({
        apiBase: API_BASE,
        gameSlug: slug,
        categorySlug,
        limit: LISTING_PAGE_SIZE,
        offset,
        filters,
        instantOnly,
        search,
        seller: sellerFilter,
      });
      const res = await fetch(url, { cache: 'no-store' });
      if (res.ok) {
        const nextData = await res.json();
        setData(prev => {
          if (!append || !prev) return nextData;
          return {
            ...nextData,
            listings: [...(prev.listings || []), ...(nextData.listings || [])],
          };
        });
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [slug, categorySlug, sellerFilter]);

  useEffect(() => {
    setActiveFilters({});
    setInstantDeliveryFilter(false);
    setSearchInput('');
    setSearchQuery('');
    fetchData({}, 0, false, false, '');
  }, [fetchData]);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setSearchQuery(searchInput), 400);
    return () => clearTimeout(timer);
  }, [searchInput]);

  function handleFilterChange(filterId, value) {
    setActiveFilters(prev => ({
      ...prev,
      [filterId]: prev[filterId] === value ? undefined : value,
    }));
  }

  function handleDropdownChange(filterId, value) {
    setActiveFilters(prev => ({
      ...prev,
      [filterId]: value || undefined,
    }));
  }

  // Re-fetch when filters, instant delivery toggle, or search change
  useEffect(() => {
    if (data) {
      fetchData(activeFilters, 0, false, instantDeliveryFilter, searchQuery);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFilters, instantDeliveryFilter, searchQuery]);

  function handleCategorySwitch(catSlug) {
    if (catSlug !== categorySlug) {
      router.push(buildSellerListingsPath({ gameSlug: slug, categorySlug: catSlug, seller: sellerFilter }));
    }
  }

  if (loading && !data) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  if (!data) return null;

  const { game, category, filters, listings, all_categories } = data;
  const pagination = data.listing_pagination;
  const listingCount = pagination?.count ?? listings?.length ?? 0;
  const allowAutoDelivery = data.allow_auto_delivery;

  return (
    <div className="container">
      {/* Seller Filter Banner */}
      {sellerFilter && (
        <div className="seller-filter-banner">
          <span>Showing listings by <Link href={buildSellerProfilePath(sellerFilter)} className="seller-filter-link">{sellerFilter}</Link></span>
          <Link href={buildSellerListingsPath({ gameSlug: slug, categorySlug })} className="seller-filter-clear">× Clear filter</Link>
        </div>
      )}

      {/* Page Header */}
      <div className="page-header">
        <div className="breadcrumb">
          <a href="/">Home</a>
          <span className="breadcrumb-sep">›</span>
          <span>{game.name}</span>
        </div>

        <div className="game-header">
          <div className="game-header-info">
            <h1>{game.name} {category.name}</h1>
          </div>
        </div>
      </div>

      {/* Category Tabs */}
      {all_categories && all_categories.length > 1 && (
        <div className="category-tabs">
          {all_categories.map((cat) => (
            <button
              key={cat.slug}
              className={`category-tab ${cat.slug === categorySlug ? 'category-tab-active' : ''}`}
              onClick={() => handleCategorySwitch(cat.slug)}
            >
              <span className="category-tab-name">{cat.name}</span>
              <span className="category-tab-count">{cat.listing_count}</span>
            </button>
          ))}
        </div>
      )}

      {/* Filters */}
      <section className="section" style={{ paddingTop: 0 }}>
        <div className="section-header">
          <h2 className="section-title">Filters</h2>
          {(Object.values(activeFilters).some(v => v) || instantDeliveryFilter || searchInput) && (
            <button
              className="btn btn-sm btn-outline"
              onClick={() => { setActiveFilters({}); setInstantDeliveryFilter(false); setSearchInput(''); }}
            >
              Clear All
            </button>
          )}
        </div>

        <div className="filters-container">
          {filters.map((filter) => (
            <div key={filter.id} className="filter-group">
              <label className="filter-label">{filter.name}</label>
              {filter.filter_type === 'button' ? (
                <div className="filter-chips">
                  {filter.options.map((opt) => (
                    <button
                      key={opt.id}
                      className={`filter-chip ${activeFilters[filter.id] === opt.value ? 'active' : ''}`}
                      onClick={() => handleFilterChange(filter.id, opt.value)}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              ) : (
                <select
                  className="filter-select"
                  value={activeFilters[filter.id] || ''}
                  onChange={(e) => handleDropdownChange(filter.id, e.target.value)}
                >
                  <option value="">All {filter.name}</option>
                  {filter.options.map((opt) => (
                    <option key={opt.id} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              )}
            </div>
          ))}

          {/* Instant Delivery Toggle (2nd last) */}
          {allowAutoDelivery && (
            <div className="filter-group">
              <label className="filter-label">Delivery</label>
              <label className="instant-delivery-filter-toggle" htmlFor="instant-delivery-filter">
                <svg className="instant-delivery-icon" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
                  <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z"/>
                </svg>
                <span>Instant Delivery</span>
                <input
                  type="checkbox"
                  id="instant-delivery-filter"
                  checked={instantDeliveryFilter}
                  onChange={(e) => setInstantDeliveryFilter(e.target.checked)}
                />
                <span className="instant-delivery-filter-slider"></span>
              </label>
            </div>
          )}

          {/* Search Bar (last) */}
          <div className="filter-group filter-group-search">
            <label className="filter-label">Search</label>
            <div className="filter-search-wrap">
              <svg className="filter-search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8"/>
                <line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              <input
                type="text"
                className="filter-search-input"
                placeholder="Search listings..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
              />
              {searchInput && (
                <button className="filter-search-clear" onClick={() => setSearchInput('')}>×</button>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Listings */}
      <section className="section" style={{ paddingTop: (filters.length > 0 || allowAutoDelivery) ? 0 : undefined }}>
        <div className="section-header">
          <h2 className="section-title">
            {listingCount} Listing{listingCount !== 1 ? 's' : ''}
          </h2>
        </div>

        {listings && listings.length > 0 ? (
          <div className="listing-cards-grid">
            {listings.map((listing) => (
              <Link
                key={listing.id}
                href={`/listing/${listing.id}`}
                className="listing-card"
              >
                {/* Card Header - Title & Price */}
                <div className="listing-card-header">
                  <h3 className="listing-card-title">{listing.title}</h3>
                  <div className="listing-card-price">PKR {Number(listing.price).toLocaleString()}</div>
                </div>

                {/* Filter Tags */}
                {listing.filter_display && Object.keys(listing.filter_display).length > 0 && (
                  <div className="listing-card-tags">
                    {Object.entries(listing.filter_display).map(([name, value]) => (
                      <span key={name} className="listing-card-tag">{value}</span>
                    ))}
                  </div>
                )}

                {/* Card Footer - Seller Info & Delivery */}
                <div className="listing-card-footer">
                  <div className="listing-card-seller">
                    <div className="listing-card-avatar-wrap">
                      <div className="listing-card-avatar">
                        {listing.seller_avatar_url ? (
                          <img src={listing.seller_avatar_url} alt={listing.seller_name} style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
                        ) : (
                          listing.seller_name?.charAt(0).toUpperCase()
                        )}
                      </div>
                      <span className={`listing-card-status-dot ${listing.seller_is_online ? 'online' : 'offline'}`} />
                    </div>
                    <span
                      className="listing-card-seller-name"
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); window.location.href = buildSellerProfilePath(listing.seller_name); }}
                    >
                      {listing.seller_name}
                    </span>
                  </div>
                  <div className={`listing-card-delivery ${listing.is_auto_delivery ? 'listing-card-delivery-instant' : ''}`}>
                    {listing.is_auto_delivery ? (
                      <>
                        <svg className="instant-delivery-icon" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
                          <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z"/>
                        </svg>
                        Instant
                      </>
                    ) : (
                      <>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <circle cx="12" cy="12" r="10"/>
                          <polyline points="12 6 12 12 16 14"/>
                        </svg>
                        {listing.delivery_time || '1-2 Hours'}
                      </>
                    )}
                  </div>
                </div>
              </Link>
            ))}
            {pagination?.next_offset !== null && pagination?.next_offset !== undefined && (
              <div className="listing-cards-load-more">
                <button
                  className="btn btn-outline btn-full"
                  onClick={() => fetchData(activeFilters, pagination.next_offset, true, instantDeliveryFilter, searchQuery)}
                  disabled={loadingMore}
                >
                  {loadingMore ? 'Loading...' : 'Load More'}
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon">🛒</div>
            <p>No listings found{Object.values(activeFilters).some(v => v) || instantDeliveryFilter || searchInput ? ' with these filters' : ''}.</p>
          </div>
        )}
      </section>
    </div>
  );
}

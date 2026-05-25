'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { API_BASE } from '@/lib/config';
import { isOnlineFromLastActive } from '@/lib/api';
import {
  buildGameCategoryListingUrl,
  buildSellerListingsPath,
  buildSellerProfilePath,
} from '@/lib/marketplaceUrls';

const LISTING_PAGE_SIZE = 48;
const PRESENCE_TICK_MS = 30000;

const SORT_OPTIONS = [
  { value: '', label: 'Recommended' },
  { value: 'price_asc', label: 'Price: Low to High' },
  { value: 'price_desc', label: 'Price: High to Low' },
  { value: 'newest', label: 'Newest First' },
  { value: 'rating', label: 'Seller Rating' },
];

function StarRating({ rating, count }) {
  if (rating === null || rating === undefined) return null;
  const fullStars = Math.floor(rating);
  const hasHalf = rating - fullStars >= 0.3;
  const stars = [];
  for (let i = 1; i <= 5; i++) {
    if (i <= fullStars) {
      stars.push(
        <svg key={i} className="listing-star listing-star-filled" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
        </svg>
      );
    } else if (i === fullStars + 1 && hasHalf) {
      stars.push(
        <svg key={i} className="listing-star listing-star-half" width="12" height="12" viewBox="0 0 24 24">
          <defs>
            <linearGradient id={`half-star-${i}`}>
              <stop offset="50%" stopColor="currentColor" />
              <stop offset="50%" stopColor="transparent" />
            </linearGradient>
          </defs>
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"
            fill={`url(#half-star-${i})`} stroke="currentColor" strokeWidth="1"/>
        </svg>
      );
    } else {
      stars.push(
        <svg key={i} className="listing-star listing-star-empty" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
        </svg>
      );
    }
  }
  return (
    <span className="listing-card-rating">
      <span className="listing-card-stars">{stars}</span>
      <span className="listing-card-rating-value">{rating.toFixed(1)}</span>
      {count > 0 && <span className="listing-card-rating-count">({count})</span>}
    </span>
  );
}

export default function GameCategoryClient({ initialData = null, initialSeller = '' }) {
  const params = useParams();
  const router = useRouter();
  const { slug, categorySlug } = params;
  const searchParams = useSearchParams();
  const sellerFilter = searchParams.get('seller') || initialSeller;
  const filterEffectReadyRef = useRef(false);
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(!initialData);
  const [loadingMore, setLoadingMore] = useState(false);
  const [activeFilters, setActiveFilters] = useState({});
  const [instantDeliveryFilter, setInstantDeliveryFilter] = useState(false);
  const [onlineSellerFilter, setOnlineSellerFilter] = useState(false);
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [presenceNow, setPresenceNow] = useState(() => Date.now());
  const hasListingData = Boolean(data);
  const loadedListingCount = data?.listings?.length || 0;

  const fetchData = useCallback(async (filters = {}, offset = 0, append = false, instantOnly = false, onlineOnly = false, search = '', ordering = '') => {
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
        onlineOnly,
        search,
        seller: sellerFilter,
        ordering,
      });
      const res = await fetch(url);
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
    setOnlineSellerFilter(false);
    setSearchInput('');
    setSearchQuery('');
    setSortBy('');
    filterEffectReadyRef.current = false;
    if (initialData) {
      setData(initialData);
      setLoading(false);
      setLoadingMore(false);
      return;
    }
    fetchData({}, 0, false, false, false, '', '');
  }, [fetchData, initialData]);

  useEffect(() => {
    const interval = setInterval(() => setPresenceNow(Date.now()), PRESENCE_TICK_MS);
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') setPresenceNow(Date.now());
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  // Background polling for listing updates (specifically seller presence)
  useEffect(() => {
    if (!hasListingData) return;

    let inFlight = false;
    let cancelled = false;
    let controller = null;

    const poll = async () => {
      if (document.visibilityState !== 'visible') return;
      if (inFlight) return;
      inFlight = true;
      controller = new AbortController();
      try {
        const url = buildGameCategoryListingUrl({
          apiBase: API_BASE,
          gameSlug: slug,
          categorySlug,
          limit: loadedListingCount || LISTING_PAGE_SIZE,
          offset: 0,
          filters: activeFilters,
          instantOnly: instantDeliveryFilter,
          onlineOnly: onlineSellerFilter,
          search: searchQuery,
          seller: sellerFilter,
          ordering: sortBy,
        });
        const res = await fetch(url, { signal: controller.signal });
        if (res.ok && !cancelled) {
          const freshData = await res.json();
          setData(prev => {
            if (cancelled) return prev;
            if (!prev) return freshData;
            const freshMap = new Map((freshData.listings || []).map(l => [l.id, l]));
            const updatedListings = (prev.listings || []).map(existing => {
              const fresh = freshMap.get(existing.id);
              if (fresh) {
                return {
                  ...existing,
                  seller_last_active: fresh.seller_last_active,
                  seller_is_online: fresh.seller_is_online,
                  price: fresh.price,
                  seller_avg_rating: fresh.seller_avg_rating,
                  seller_review_count: fresh.seller_review_count,
                  seller_avatar_url: fresh.seller_avatar_url,
                };
              }
              return existing;
            });
            return {
              ...prev,
              listings: updatedListings,
            };
          });
        }
      } catch (err) {
        if (err?.name !== 'AbortError') {
          console.error('Failed to background poll listings presence:', err);
        }
      } finally {
        inFlight = false;
        controller = null;
      }
    };

    const interval = setInterval(poll, PRESENCE_TICK_MS);
    return () => {
      cancelled = true;
      if (controller) controller.abort();
      clearInterval(interval);
    };
  }, [hasListingData, loadedListingCount, slug, categorySlug, activeFilters, instantDeliveryFilter, onlineSellerFilter, searchQuery, sellerFilter, sortBy]);

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

  // Re-fetch when filters, instant delivery toggle, online seller toggle, search, or sort change
  useEffect(() => {
    if (!filterEffectReadyRef.current) {
      filterEffectReadyRef.current = true;
      return;
    }
    if (data) {
      fetchData(activeFilters, 0, false, instantDeliveryFilter, onlineSellerFilter, searchQuery, sortBy);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFilters, instantDeliveryFilter, onlineSellerFilter, searchQuery, sortBy]);

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
        <div className="filters-toggle-header">
          <button
            className="filters-toggle-btn"
            onClick={() => setFiltersOpen(prev => !prev)}
            aria-expanded={filtersOpen}
            aria-controls="filters-panel"
          >
            <svg className="filters-toggle-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="4" y1="6" x2="20" y2="6"/>
              <line x1="4" y1="12" x2="20" y2="12"/>
              <line x1="4" y1="18" x2="20" y2="18"/>
              <circle cx="8" cy="6" r="2" fill="currentColor"/>
              <circle cx="16" cy="12" r="2" fill="currentColor"/>
              <circle cx="10" cy="18" r="2" fill="currentColor"/>
            </svg>
            <span>Filters</span>
            <svg className={`filters-toggle-chevron ${filtersOpen ? 'filters-toggle-chevron-open' : ''}`} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </button>
          {(Object.values(activeFilters).some(v => v) || instantDeliveryFilter || onlineSellerFilter || searchInput) && (
            <button
              className="btn btn-sm btn-outline"
              onClick={() => { setActiveFilters({}); setInstantDeliveryFilter(false); setOnlineSellerFilter(false); setSearchInput(''); }}
            >
              Clear All
            </button>
          )}
        </div>

        <div
          id="filters-panel"
          className={`filters-collapsible ${filtersOpen ? 'filters-collapsible-open' : ''}`}
        >
          <div className="filters-container">
            {filters.map((filter) => (
              <div key={filter.id} className="filter-group">
                <label className="filter-label" htmlFor={`filter-${filter.id}`}>{filter.name}</label>
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
                    id={`filter-${filter.id}`}
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

            {/* Online Sellers Toggle */}
            <div className="filter-group">
              <label className="filter-label">Seller Status</label>
              <label className="online-seller-filter-toggle" htmlFor="online-seller-filter">
                <input
                  type="checkbox"
                  id="online-seller-filter"
                  checked={onlineSellerFilter}
                  onChange={(e) => setOnlineSellerFilter(e.target.checked)}
                />
                <span className="online-seller-filter-dot"></span>
                <span>Online Sellers</span>
                <span className="online-seller-filter-slider"></span>
              </label>
            </div>

            {/* Instant Delivery Toggle */}
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
                  <button className="filter-search-clear" onClick={() => setSearchInput('')} aria-label="Clear search">×</button>
                )}
              </div>
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
          <div className="listing-sort-wrap" id="listing-sort">
            <svg className="listing-sort-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="4" y1="6" x2="20" y2="6"/>
              <line x1="4" y1="12" x2="14" y2="12"/>
              <line x1="4" y1="18" x2="8" y2="18"/>
            </svg>
            <select
              className="listing-sort-select"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              id="listing-sort-select"
              aria-label="Sort listings"
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
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
                          <img src={listing.seller_avatar_url} alt={listing.seller_name} loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
                        ) : (
                          listing.seller_name?.charAt(0).toUpperCase()
                        )}
                      </div>
                      <span className={`listing-card-status-dot ${isOnlineFromLastActive(listing.seller_last_active, presenceNow) ? 'online' : 'offline'}`} />
                    </div>
                    <div className="listing-card-seller-info">
                      <span
                        className="listing-card-seller-name"
                        onClick={(e) => { e.preventDefault(); e.stopPropagation(); window.location.href = buildSellerProfilePath(listing.seller_name); }}
                      >
                        {listing.seller_name}
                      </span>
                      <StarRating rating={listing.seller_avg_rating} count={listing.seller_review_count} />
                    </div>
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
                  onClick={() => fetchData(activeFilters, pagination.next_offset, true, instantDeliveryFilter, onlineSellerFilter, searchQuery, sortBy)}
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
            <p>No listings found{Object.values(activeFilters).some(v => v) || instantDeliveryFilter || onlineSellerFilter || searchInput ? ' with these filters' : ''}.</p>
          </div>
        )}
      </section>
    </div>
  );
}

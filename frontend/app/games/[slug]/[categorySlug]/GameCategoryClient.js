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
import { isFilterVisible, pruneHiddenFilterValues } from '@/lib/filterDependencies';
import ItemRequestForm from '@/components/ItemRequestForm';

const LISTING_PAGE_SIZE = 48;
const PRESENCE_TICK_MS = 30000;

const SORT_OPTIONS = [
  { value: '', label: 'Recommended' },
  { value: 'price_asc', label: 'Price: Low to High' },
  { value: 'price_desc', label: 'Price: High to Low' },
  { value: 'newest', label: 'Newest First' },
  { value: 'rating', label: 'Seller Rating' },
];

const OFFER_SORT_OPTIONS = [
  { value: '', label: 'Best Offer' },
  { value: 'price_asc', label: 'Price: Low to High' },
  { value: 'price_desc', label: 'Price: High to Low' },
  { value: 'delivery', label: 'Fastest Delivery' },
  { value: 'rating', label: 'Seller Rating' },
  { value: 'newest', label: 'Newest First' },
];

const CURRENCY_SORT_OPTIONS = [
  { value: '', label: 'Recommended' },
  { value: 'price_asc', label: 'Cheapest first' },
  { value: 'min_qty', label: 'Lowest min. quantity' },
];

// Per-unit prices can be tiny (e.g., PKR 1.4 / M) — keep up to 2 decimals.
const formatUnitPrice = (n) =>
  Number(n).toLocaleString('en-PK', { maximumFractionDigits: 2 });
const formatAmount = (n) => Number(n).toLocaleString('en-PK');
const CURRENCY_DESC_CLAMP_LENGTH = 220;

function DeliveryTimeBadge({ listing }) {
  return listing.is_auto_delivery ? (
    <span className="offer-delivery offer-delivery-instant">
      <svg className="instant-delivery-icon" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
        <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z"/>
      </svg>
      Instant
    </span>
  ) : (
    <span className="offer-delivery">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <polyline points="12 6 12 12 16 14"/>
      </svg>
      {listing.delivery_time || '10-15 Minutes'}
    </span>
  );
}

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
  const [selectedOption, setSelectedOption] = useState(initialData?.selected_option_id ?? null);
  const [buyboxInstructionsOpen, setBuyboxInstructionsOpen] = useState(false);
  const [expandedInstructions, setExpandedInstructions] = useState(() => new Set());
  const [selectedCurrencyId, setSelectedCurrencyId] = useState(null);
  const [currencyQty, setCurrencyQty] = useState('');
  const [heroDescOpen, setHeroDescOpen] = useState(false);
  const currencyHeroRef = useRef(null);
  const hasListingData = Boolean(data);
  const loadedListingCount = data?.listings?.length || 0;

  const fetchData = useCallback(async (filters = {}, offset = 0, append = false, instantOnly = false, onlineOnly = false, search = '', ordering = '', option = null) => {
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
        option: option || '',
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
        if (!append && nextData.listing_mode === 'offer' && !option) {
          // First fetch without an explicit option: the backend picked the
          // default option for us — adopt it so option cards highlight.
          setSelectedOption(nextData.selected_option_id ?? null);
        }
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
      setSelectedOption(initialData.selected_option_id ?? null);
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
          option: selectedOption || '',
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
                  quantity: fresh.quantity,
                  min_quantity: fresh.min_quantity,
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
  }, [hasListingData, loadedListingCount, slug, categorySlug, activeFilters, instantDeliveryFilter, onlineSellerFilter, searchQuery, sellerFilter, sortBy, selectedOption]);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setSearchQuery(searchInput), 400);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Currency mode: keep a valid "current offer" selected. When fresh data no
  // longer contains the selection (filter/sort change), fall back to the top
  // offer and reset the amount to its minimum.
  useEffect(() => {
    if (!data || data.listing_mode !== 'currency') return;
    const list = data.listings || [];
    const offer = list.find((l) => l.id === selectedCurrencyId) || list[0];
    if (!offer) return;
    if (offer.id !== selectedCurrencyId) {
      setSelectedCurrencyId(offer.id);
      setCurrencyQty(String(offer.min_quantity || 1));
      setHeroDescOpen(false);
    }
  }, [data, selectedCurrencyId]);

  function handleFilterChange(filterId, value) {
    // Pruning drops selections on dependent filters that the change just hid.
    setActiveFilters(prev => pruneHiddenFilterValues(data?.filters || [], {
      ...prev,
      [filterId]: prev[filterId] === value ? undefined : value,
    }));
  }

  function handleDropdownChange(filterId, value) {
    setActiveFilters(prev => pruneHiddenFilterValues(data?.filters || [], {
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
      fetchData(activeFilters, 0, false, instantDeliveryFilter, onlineSellerFilter, searchQuery, sortBy, selectedOption);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFilters, instantDeliveryFilter, onlineSellerFilter, searchQuery, sortBy]);

  function handleCategorySwitch(catSlug) {
    if (catSlug !== categorySlug) {
      router.push(buildSellerListingsPath({ gameSlug: slug, categorySlug: catSlug, seller: sellerFilter }));
    }
  }

  function toggleInstructions(listingId) {
    setExpandedInstructions(prev => {
      const next = new Set(prev);
      if (next.has(listingId)) {
        next.delete(listingId);
      } else {
        next.add(listingId);
      }
      return next;
    });
  }

  function handleCurrencySelect(listing) {
    setSelectedCurrencyId(listing.id);
    setCurrencyQty(String(listing.min_quantity || 1));
    setHeroDescOpen(false);
    currencyHeroRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function handleOptionSelect(optionId) {
    if (optionId === selectedOption) return;
    setSelectedOption(optionId);
    setBuyboxInstructionsOpen(false);
    setExpandedInstructions(new Set());
    // Shallow URL update so the selection is shareable without a navigation
    const query = new URLSearchParams(searchParams.toString());
    query.set('option', String(optionId));
    window.history.replaceState(null, '', `${window.location.pathname}?${query.toString()}`);
    fetchData(activeFilters, 0, false, instantDeliveryFilter, onlineSellerFilter, searchQuery, sortBy, optionId);
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
  const isOfferMode = data.listing_mode === 'offer';
  const isCurrencyMode = data.listing_mode === 'currency';
  const unitName = data.unit_name || '';
  const currencyListings = isCurrencyMode ? (listings || []) : [];
  const currentOffer = isCurrencyMode
    ? currencyListings.find((l) => l.id === selectedCurrencyId) || currencyListings[0] || null
    : null;
  const offerMinQty = currentOffer?.min_quantity || 1;
  const offerStock = currentOffer?.quantity ?? null;
  const parsedQty = parseInt(currencyQty, 10);
  const qtyValid = Number.isFinite(parsedQty)
    && parsedQty >= offerMinQty
    && (offerStock === null || parsedQty <= offerStock);
  const currencyTotal = currentOffer && qtyValid ? Number(currentOffer.price) * parsedQty : null;
  const currencyHeroText = currentOffer
    ? [currentOffer.delivery_instructions, currentOffer.description].filter(Boolean).join('\n\n')
    : '';
  const heroTextClamped = currencyHeroText.length > CURRENCY_DESC_CLAMP_LENGTH;
  const options = data.options || [];
  const selectedOptionData = options.find((opt) => opt.id === selectedOption) || null;
  const bestOffer = isOfferMode && listings?.length > 0 ? listings[0] : null;
  const otherOffers = isOfferMode ? (listings || []).slice(1) : [];
  const otherSellerCount = Math.max(listingCount - 1, 0);
  // Dependent filters stay hidden until their parent filter holds the
  // triggering option (e.g., Region — Keys only shows when Method = Digital Key).
  const visibleFilters = filters.filter((f) => isFilterVisible(f, activeFilters));
  // Gate filters (e.g., Region for region-locked gift cards) must be chosen
  // before offers are shown. Admin marks them via "require selection".
  const gateFilters = isOfferMode ? visibleFilters.filter((f) => f.require_selection) : [];
  const missingGateFilters = gateFilters.filter((f) => !activeFilters[f.id]);
  const gateSatisfied = missingGateFilters.length === 0;
  const hasGateSteps = gateFilters.length > 0;
  const panelFilters = isOfferMode ? visibleFilters.filter((f) => !f.require_selection) : visibleFilters;
  const hasActiveFilters = Object.values(activeFilters).some(v => v)
    || instantDeliveryFilter || onlineSellerFilter || Boolean(searchInput);

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
              {cat.listing_count > 0 && (
                <span className="category-tab-count">{cat.listing_count}</span>
              )}
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
          {hasActiveFilters && (
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
            {panelFilters.map((filter) => (
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

            {/* Search Bar (last) — searching titles is meaningless when sellers
                compete on identical items (offer/currency modes) */}
            {!isOfferMode && !isCurrencyMode && (
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
            )}
          </div>
        </div>
      </section>

      {/* Offer mode: option grid + buy box + competing seller offers */}
      {isOfferMode && (
      <section className="section" style={{ paddingTop: 0 }}>
        {options.length === 0 && !Object.values(activeFilters).some(Boolean) ? (
          <>
            <div className="empty-state">
              <div className="empty-state-icon">🧩</div>
              <p>No options are available in this category yet.</p>
            </div>
            <ItemRequestForm
              gameSlug={slug}
              categorySlug={categorySlug}
              gameName={game.name}
              categoryName={category.name}
            />
          </>
        ) : (
          <div className={`offer-layout ${hasGateSteps ? 'offer-layout-gated' : ''}`}>
            {/* Gate filters: must be selected before offers are shown */}
            {hasGateSteps && (
              <div className="offer-gate-card">
                {gateFilters.map((filter, index) => (
                  <div key={filter.id} className="offer-gate-filter">
                    <label className="offer-gate-label" htmlFor={`offer-gate-${filter.id}`}>
                      <span className="offer-step-badge">{index + 1}</span>
                      Select {filter.name}
                      <span className="offer-gate-required">*</span>
                    </label>
                    {filter.filter_type === 'button' ? (
                      <div className="filter-chips">
                        {filter.options.map((opt) => (
                          <button
                            key={opt.id}
                            type="button"
                            className={`filter-chip ${activeFilters[filter.id] === opt.value ? 'active' : ''}`}
                            onClick={() => handleFilterChange(filter.id, opt.value)}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <select
                        id={`offer-gate-${filter.id}`}
                        className="filter-select offer-gate-select"
                        value={activeFilters[filter.id] || ''}
                        onChange={(e) => handleDropdownChange(filter.id, e.target.value)}
                      >
                        <option value="">Choose {filter.name}...</option>
                        {filter.options.map((opt) => (
                          <option key={opt.id} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Option cards */}
            <div className="offer-options-card">
              <h2 className="offer-options-title">
                {hasGateSteps && <span className="offer-step-badge">{gateFilters.length + 1}</span>}
                Options
              </h2>
              {options.length === 0 && (
                <div className="empty-state" style={{ padding: '24px 0' }}>
                  <p>Nothing is available for this selection right now — try a different choice above.</p>
                </div>
              )}
              <div className={`offer-options-grid ${!gateSatisfied ? 'offer-options-grid-disabled' : ''}`}>
                {options.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    className={`offer-option-card ${opt.id === selectedOption ? 'offer-option-card-selected' : ''}`}
                    onClick={() => handleOptionSelect(opt.id)}
                    disabled={!gateSatisfied}
                  >
                    {opt.is_popular && <span className="offer-option-popular">★ Popular</span>}
                    {opt.id === selectedOption && (
                      <span className="offer-option-check" aria-hidden="true">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="20 6 9 17 4 12"/>
                        </svg>
                      </span>
                    )}
                    {opt.icon_url && (
                      <img src={opt.icon_url} alt="" className="offer-option-icon" loading="lazy" />
                    )}
                    <span className="offer-option-name">{opt.name}</span>
                    {opt.min_price !== null && opt.min_price !== undefined ? (
                      <span className="offer-option-price">From Rs {Number(opt.min_price).toLocaleString()}</span>
                    ) : (
                      <span className="offer-option-price offer-option-price-empty">No offers yet</span>
                    )}
                    {opt.offer_count > 0 && (
                      <span className="offer-option-count">{opt.offer_count} seller{opt.offer_count !== 1 ? 's' : ''}</span>
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* Buy box for the best offer of the selected option */}
            <aside className="offer-sidebar">
              {!gateSatisfied ? (
                <div className="offer-buybox">
                  <div className="empty-state" style={{ padding: '24px 12px' }}>
                    <div className="empty-state-icon">🌍</div>
                    <p>Select {missingGateFilters.map((f) => f.name).join(' and ')} to see offers.</p>
                  </div>
                </div>
              ) : loading ? (
                <div className="offer-buybox">
                  <div className="loading"><div className="loading-spinner"></div> Loading...</div>
                </div>
              ) : bestOffer ? (
                <div className="offer-buybox">
                  {selectedOptionData && (
                    <div className="offer-buybox-option">
                      {selectedOptionData.icon_url && (
                        <img src={selectedOptionData.icon_url} alt="" className="offer-buybox-option-icon" />
                      )}
                      <span>{selectedOptionData.name}</span>
                    </div>
                  )}

                  {bestOffer.filter_display && Object.entries(bestOffer.filter_display).map(([name, value]) => (
                    <div key={name} className="offer-buybox-row">
                      <span className="offer-buybox-label">{name}</span>
                      <span className="offer-buybox-value">{value}</span>
                    </div>
                  ))}
                  <div className="offer-buybox-row">
                    <span className="offer-buybox-label">Delivery time</span>
                    <DeliveryTimeBadge listing={bestOffer} />
                  </div>
                  {bestOffer.delivery_instructions && (
                    <div className="offer-buybox-instructions">
                      <button
                        type="button"
                        className="offer-instructions-toggle"
                        onClick={() => setBuyboxInstructionsOpen(prev => !prev)}
                        aria-expanded={buyboxInstructionsOpen}
                      >
                        <span className="offer-buybox-label">Delivery instructions</span>
                        <svg className={`offer-instructions-chevron ${buyboxInstructionsOpen ? 'offer-instructions-chevron-open' : ''}`} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="6 9 12 15 18 9"/>
                        </svg>
                      </button>
                      {buyboxInstructionsOpen && (
                        <p className="offer-instructions-text">{bestOffer.delivery_instructions}</p>
                      )}
                    </div>
                  )}
                  <div className="offer-buybox-row offer-buybox-total">
                    <span className="offer-buybox-label">Total</span>
                    <span className="offer-buybox-price">PKR {Number(bestOffer.price).toLocaleString()}</span>
                  </div>

                  <Link href={`/listing/${bestOffer.id}?buy=1`} className="btn btn-primary btn-full buy-now-btn">
                    Buy Now
                  </Link>

                  {category.buyer_protection_enabled && (
                    <div className="offer-buybox-protection">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                        <polyline points="9 12 11 14 15 10"/>
                      </svg>
                      <span>Buyer Protection included</span>
                    </div>
                  )}

                  <div className="offer-buybox-seller">
                    <div className="listing-card-avatar-wrap">
                      <div className="listing-card-avatar">
                        {bestOffer.seller_avatar_url ? (
                          <img src={bestOffer.seller_avatar_url} alt={bestOffer.seller_name} loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
                        ) : (
                          bestOffer.seller_name?.charAt(0).toUpperCase()
                        )}
                      </div>
                      <span className={`listing-card-status-dot ${isOnlineFromLastActive(bestOffer.seller_last_active, presenceNow) ? 'online' : 'offline'}`} />
                    </div>
                    <div className="offer-buybox-seller-info">
                      <Link href={buildSellerProfilePath(bestOffer.seller_name)} className="offer-seller-name">
                        {bestOffer.seller_name}
                      </Link>
                      <StarRating rating={bestOffer.seller_avg_rating} count={bestOffer.seller_review_count} />
                    </div>
                  </div>
                </div>
              ) : (
                <div className="offer-buybox">
                  <div className="empty-state" style={{ padding: '24px 12px' }}>
                    <div className="empty-state-icon">🛒</div>
                    <p>No sellers are offering {selectedOptionData ? selectedOptionData.name : 'this option'} right now.</p>
                  </div>
                </div>
              )}
            </aside>

            {/* Competing seller offers */}
            <div className="offer-sellers">
              <div className="section-header">
                <h2 className="section-title">
                  {gateSatisfied ? `Other sellers (${otherSellerCount})` : 'Other sellers'}
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
                    aria-label="Sort offers"
                  >
                    {OFFER_SORT_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              {!gateSatisfied ? (
                <p className="offer-no-others">
                  Select {missingGateFilters.map((f) => f.name).join(' and ')} above to compare seller offers.
                </p>
              ) : otherOffers.length > 0 ? (
                <div className="offer-seller-list">
                  {otherOffers.map((offer) => (
                    <div key={offer.id} className="offer-seller-row">
                      <div className="offer-seller-row-main">
                        <div className="offer-seller-row-seller">
                          <div className="listing-card-avatar-wrap">
                            <div className="listing-card-avatar">
                              {offer.seller_avatar_url ? (
                                <img src={offer.seller_avatar_url} alt={offer.seller_name} loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
                              ) : (
                                offer.seller_name?.charAt(0).toUpperCase()
                              )}
                            </div>
                            <span className={`listing-card-status-dot ${isOnlineFromLastActive(offer.seller_last_active, presenceNow) ? 'online' : 'offline'}`} />
                          </div>
                          <div className="offer-seller-row-info">
                            <Link href={buildSellerProfilePath(offer.seller_name)} className="offer-seller-name">
                              {offer.seller_name}
                            </Link>
                            <StarRating rating={offer.seller_avg_rating} count={offer.seller_review_count} />
                          </div>
                        </div>
                        <div className="offer-seller-row-delivery">
                          <span className="offer-seller-row-label">Delivery time</span>
                          <DeliveryTimeBadge listing={offer} />
                        </div>
                        <div className="offer-seller-row-price">PKR {Number(offer.price).toLocaleString()}</div>
                        <Link href={`/listing/${offer.id}?buy=1`} className="btn btn-outline offer-seller-row-buy">
                          Buy now
                        </Link>
                        {offer.delivery_instructions ? (
                          <button
                            type="button"
                            className="offer-instructions-toggle offer-seller-row-instructions-btn"
                            onClick={() => toggleInstructions(offer.id)}
                            aria-expanded={expandedInstructions.has(offer.id)}
                          >
                            Delivery instructions
                            <svg className={`offer-instructions-chevron ${expandedInstructions.has(offer.id) ? 'offer-instructions-chevron-open' : ''}`} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                              <polyline points="6 9 12 15 18 9"/>
                            </svg>
                          </button>
                        ) : (
                          <span className="offer-seller-row-instructions-btn" />
                        )}
                      </div>
                      {expandedInstructions.has(offer.id) && offer.delivery_instructions && (
                        <div className="offer-seller-row-instructions">
                          <span className="offer-seller-row-instructions-title">Delivery instructions</span>
                          <p className="offer-instructions-text">{offer.delivery_instructions}</p>
                        </div>
                      )}
                    </div>
                  ))}
                  {pagination?.next_offset !== null && pagination?.next_offset !== undefined && (
                    <button
                      className="btn btn-outline btn-full"
                      onClick={() => fetchData(activeFilters, pagination.next_offset, true, instantDeliveryFilter, onlineSellerFilter, searchQuery, sortBy, selectedOption)}
                      disabled={loadingMore}
                    >
                      {loadingMore ? 'Loading...' : 'Load More'}
                    </button>
                  )}
                </div>
              ) : (
                <p className="offer-no-others">
                  {bestOffer ? 'No other sellers for this option right now.' : 'Be the first seller to make an offer for this option.'}
                </p>
              )}
            </div>
          </div>
        )}
      </section>
      )}

      {/* Currency mode: current offer hero + competing sellers (Eldorado-style) */}
      {isCurrencyMode && (
      <section className="section" style={{ paddingTop: 0 }}>
        {currencyListings.length === 0 ? (
          <>
            <div className="empty-state">
              <div className="empty-state-icon">🪙</div>
              <p>No sellers are offering {game.name} {category.name} right now{hasActiveFilters ? ' with these filters' : ''}.</p>
            </div>
            {!hasActiveFilters && !sellerFilter && (
              <ItemRequestForm
                gameSlug={slug}
                categorySlug={categorySlug}
                gameName={game.name}
                categoryName={category.name}
              />
            )}
          </>
        ) : currentOffer && (
          <>
            <div className="currency-layout" ref={currencyHeroRef}>
              {/* Current offer: seller card */}
              <div className="currency-hero-card">
                <div className="currency-hero-seller">
                  <div className="listing-card-avatar-wrap">
                    <div className="listing-card-avatar currency-hero-avatar">
                      {currentOffer.seller_avatar_url ? (
                        <img src={currentOffer.seller_avatar_url} alt={currentOffer.seller_name} loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
                      ) : (
                        currentOffer.seller_name?.charAt(0).toUpperCase()
                      )}
                    </div>
                    <span className={`listing-card-status-dot ${isOnlineFromLastActive(currentOffer.seller_last_active, presenceNow) ? 'online' : 'offline'}`} />
                  </div>
                  <div className="currency-hero-seller-info">
                    <Link href={buildSellerProfilePath(currentOffer.seller_name)} className="offer-seller-name">
                      {currentOffer.seller_name}
                    </Link>
                    <span className="currency-hero-rating">
                      <StarRating rating={currentOffer.seller_avg_rating} count={0} />
                      {currentOffer.seller_review_count > 0 && (
                        <Link href={buildSellerProfilePath(currentOffer.seller_name)} className="currency-hero-reviews">
                          {formatAmount(currentOffer.seller_review_count)} review{currentOffer.seller_review_count !== 1 ? 's' : ''}
                        </Link>
                      )}
                    </span>
                  </div>
                </div>

                <div className="currency-hero-row">
                  <span className="offer-buybox-label">Delivery time</span>
                  <DeliveryTimeBadge listing={currentOffer} />
                </div>

                {currencyHeroText && (
                  <div className="currency-hero-desc-wrap">
                    <p className={`currency-hero-desc ${heroTextClamped && !heroDescOpen ? 'currency-hero-desc-clamped' : ''}`}>
                      {currencyHeroText}
                    </p>
                    {heroTextClamped && (
                      <button
                        type="button"
                        className="btn btn-sm btn-outline"
                        onClick={() => setHeroDescOpen((prev) => !prev)}
                      >
                        {heroDescOpen ? 'Read less' : 'Read more'}
                      </button>
                    )}
                  </div>
                )}
              </div>

              {/* Current offer: price panel */}
              <aside className="currency-panel">
                <div className="currency-panel-price-row">
                  <span className="offer-buybox-label">Price</span>
                  <span className="currency-unit-price">
                    PKR {formatUnitPrice(currentOffer.price)}
                    {unitName && <span className="currency-unit-suffix"> / {unitName}</span>}
                  </span>
                </div>

                <div className="currency-qty-box">
                  <button
                    type="button"
                    className="currency-qty-btn"
                    aria-label="Decrease amount"
                    onClick={() => setCurrencyQty(String(Math.max(offerMinQty, (Number.isFinite(parsedQty) ? parsedQty : offerMinQty + 1) - 1)))}
                    disabled={Number.isFinite(parsedQty) && parsedQty <= offerMinQty}
                  >−</button>
                  <div className="currency-qty-input-wrap">
                    <input
                      type="number"
                      className="currency-qty-input"
                      inputMode="numeric"
                      min={offerMinQty}
                      max={offerStock ?? undefined}
                      value={currencyQty}
                      onChange={(e) => setCurrencyQty(e.target.value)}
                      aria-label={`Amount${unitName ? ` in ${unitName}` : ''}`}
                    />
                    {unitName && <span className="currency-qty-unit">{unitName}</span>}
                  </div>
                  <button
                    type="button"
                    className="currency-qty-btn"
                    aria-label="Increase amount"
                    onClick={() => setCurrencyQty(String(Math.min(offerStock ?? Infinity, (Number.isFinite(parsedQty) ? parsedQty : offerMinQty - 1) + 1)))}
                    disabled={Number.isFinite(parsedQty) && offerStock !== null && parsedQty >= offerStock}
                  >+</button>
                </div>

                <div className="currency-qty-meta">
                  <span>Min. qty.: {formatAmount(offerMinQty)} {unitName}</span>
                  {offerStock !== null && <span>In stock: {formatAmount(offerStock)} {unitName}</span>}
                </div>

                {currencyQty !== '' && !qtyValid && (
                  <div className="currency-qty-error">
                    {!Number.isFinite(parsedQty) || parsedQty < offerMinQty
                      ? `Minimum purchase is ${formatAmount(offerMinQty)} ${unitName}.`
                      : `Only ${formatAmount(offerStock)} ${unitName} in stock.`}
                  </div>
                )}

                {qtyValid ? (
                  <Link
                    href={`/listing/${currentOffer.id}?buy=1&qty=${parsedQty}`}
                    className="btn btn-primary btn-full buy-now-btn"
                  >
                    PKR {formatUnitPrice(currencyTotal)} | Buy now
                  </Link>
                ) : (
                  <button type="button" className="btn btn-primary btn-full buy-now-btn" disabled>
                    Buy now
                  </button>
                )}

                {category.buyer_protection_enabled && (
                  <div className="offer-buybox-protection">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                      <polyline points="9 12 11 14 15 10"/>
                    </svg>
                    <span>Buyer Protection included</span>
                  </div>
                )}
              </aside>
            </div>

            {/* All competing sellers */}
            <div className="currency-sellers">
              <div className="section-header">
                <h2 className="section-title">Other sellers ({Math.max(listingCount - 1, 0)})</h2>
              </div>

              <div className="currency-sort-chips">
                {CURRENCY_SORT_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    className={`filter-chip ${sortBy === opt.value ? 'active' : ''}`}
                    onClick={() => setSortBy(opt.value)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>

              <div className="currency-seller-list">
                {currencyListings.map((listing) => {
                  const isCurrent = listing.id === currentOffer.id;
                  return (
                    <div
                      key={listing.id}
                      className={`currency-seller-row ${isCurrent ? 'currency-seller-row-current' : ''}`}
                      role="button"
                      tabIndex={0}
                      onClick={() => { if (!isCurrent) handleCurrencySelect(listing); }}
                      onKeyDown={(e) => {
                        if ((e.key === 'Enter' || e.key === ' ') && !isCurrent) {
                          e.preventDefault();
                          handleCurrencySelect(listing);
                        }
                      }}
                    >
                      {isCurrent && <span className="currency-current-badge">Current offer</span>}
                      <div className="currency-seller-row-main">
                        <div className="offer-seller-row-seller">
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
                          <div className="offer-seller-row-info">
                            <Link
                              href={buildSellerProfilePath(listing.seller_name)}
                              className="offer-seller-name"
                              onClick={(e) => e.stopPropagation()}
                            >
                              {listing.seller_name}
                            </Link>
                            <StarRating rating={listing.seller_avg_rating} count={listing.seller_review_count} />
                          </div>
                        </div>
                        <div className="currency-seller-row-stat">
                          <span className="offer-seller-row-label">In stock</span>
                          <span className="currency-seller-row-value">
                            {listing.quantity === null ? '∞' : formatAmount(listing.quantity)} {unitName}
                          </span>
                        </div>
                        <div className="currency-seller-row-stat">
                          <span className="offer-seller-row-label">Min. qty.</span>
                          <span className="currency-seller-row-value">
                            {formatAmount(listing.min_quantity || 1)} {unitName}
                          </span>
                        </div>
                        <div className="currency-seller-row-stat">
                          <span className="offer-seller-row-label">Delivery time</span>
                          <DeliveryTimeBadge listing={listing} />
                        </div>
                        <div className="currency-seller-row-price">
                          PKR {formatUnitPrice(listing.price)}
                          {unitName && <span className="currency-unit-suffix"> / {unitName}</span>}
                        </div>
                      </div>
                    </div>
                  );
                })}
                {pagination?.next_offset !== null && pagination?.next_offset !== undefined && (
                  <button
                    className="btn btn-outline btn-full"
                    onClick={() => fetchData(activeFilters, pagination.next_offset, true, instantDeliveryFilter, onlineSellerFilter, searchQuery, sortBy)}
                    disabled={loadingMore}
                  >
                    {loadingMore ? 'Loading...' : 'Load More'}
                  </button>
                )}
              </div>
            </div>
          </>
        )}
      </section>
      )}

      {/* Listings */}
      {!isOfferMode && !isCurrencyMode && (
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
                        {listing.delivery_time || '10-15 Minutes'}
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
          <>
            <div className="empty-state">
              <div className="empty-state-icon">🛒</div>
              <p>No listings found{hasActiveFilters || sellerFilter ? ' with these filters' : ' here yet'}.</p>
            </div>
            {!hasActiveFilters && !sellerFilter && (
              <ItemRequestForm
                gameSlug={slug}
                categorySlug={categorySlug}
                gameName={game.name}
                categoryName={category.name}
              />
            )}
          </>
        )}
      </section>
      )}
    </div>
  );
}

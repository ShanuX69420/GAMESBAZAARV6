'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { API_BASE } from '@/lib/config';

const LISTING_PAGE_SIZE = 48;

export default function GameCategoryPage() {
  const params = useParams();
  const { slug, categorySlug } = params;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [activeFilters, setActiveFilters] = useState({});

  const fetchData = useCallback(async (filters = {}, offset = 0, append = false) => {
    if (append) {
      setLoadingMore(true);
    } else {
      setLoading(true);
    }
    try {
      const query = new URLSearchParams({
        limit: String(LISTING_PAGE_SIZE),
        offset: String(offset),
      });
      Object.entries(filters)
        .filter(([, value]) => value)
        .forEach(([key, value]) => query.set(`filter_${key}`, value));

      const url = `${API_BASE}/api/games/${slug}/${categorySlug}/?${query.toString()}`;
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
  }, [slug, categorySlug]);

  useEffect(() => {
    fetchData(activeFilters, 0, false);
  }, [fetchData, activeFilters]);

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

  if (loading && !data) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  if (!data) return null;

  const { game, category, filters, listings } = data;
  const pagination = data.listing_pagination;
  const listingCount = pagination?.count ?? listings?.length ?? 0;

  return (
    <div className="container">
      {/* Page Header */}
      <div className="page-header">
        <div className="breadcrumb">
          <a href="/">Home</a>
          <span className="breadcrumb-sep">›</span>
          <a href={`/games/${game.slug}`}>{game.name}</a>
          <span className="breadcrumb-sep">›</span>
          <span>{category.name}</span>
        </div>

        <div className="game-header">
          <div className="game-header-icon">
            {category.icon || '📦'}
          </div>
          <div className="game-header-info">
            <h1>{game.name} — {category.name}</h1>
            {category.description && <p>{category.description}</p>}
          </div>
        </div>
      </div>

      {/* Filters */}
      {filters.length > 0 && (
        <section className="section">
          <div className="section-header">
            <h2 className="section-title">Filters</h2>
            {Object.values(activeFilters).some(v => v) && (
              <button
                className="btn btn-sm btn-outline"
                onClick={() => setActiveFilters({})}
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
          </div>
        </section>
      )}

      {/* Listings */}
      <section className="section">
        <div className="section-header">
          <h2 className="section-title">
            {listingCount} Listing{listingCount !== 1 ? 's' : ''}
          </h2>
        </div>

        {listings && listings.length > 0 ? (
          <div className="listings-list">
            {listings.map((listing) => (
              <Link
                key={listing.id}
                href={`/listing/${listing.id}`}
                className="listing-row"
              >
                <div className="listing-row-info">
                  <div className="listing-row-title">{listing.title}</div>
                  <div className="listing-row-meta">
                    <span onClick={(e) => { e.preventDefault(); e.stopPropagation(); window.location.href = `/seller/${listing.seller_name}`; }} style={{ color: 'var(--green-600)', cursor: 'pointer' }}>{listing.seller_name}</span>
                    {listing.filter_display && Object.entries(listing.filter_display).map(([name, value]) => (
                      <span key={name} className="listing-row-tag">{value}</span>
                    ))}
                  </div>
                </div>
                <div className="listing-row-price">PKR {listing.price}</div>
              </Link>
            ))}
            {pagination?.next_offset !== null && pagination?.next_offset !== undefined && (
              <button
                className="btn btn-outline btn-full"
                style={{ marginTop: '16px' }}
                onClick={() => fetchData(activeFilters, pagination.next_offset, true)}
                disabled={loadingMore}
              >
                {loadingMore ? 'Loading...' : 'Load More'}
              </button>
            )}
          </div>
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon">🛒</div>
            <p>No listings found{Object.values(activeFilters).some(v => v) ? ' with these filters' : ''}.</p>
          </div>
        )}
      </section>
    </div>
  );
}

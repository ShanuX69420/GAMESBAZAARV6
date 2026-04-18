'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { getGameIcon } from '@/lib/icons';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

export default function GameCategoryPage() {
  const params = useParams();
  const { slug, categorySlug } = params;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeFilters, setActiveFilters] = useState({});

  const fetchData = useCallback(async (filters = {}) => {
    setLoading(true);
    try {
      const filterParams = Object.entries(filters)
        .filter(([, v]) => v)
        .map(([k, v]) => `filter_${k}=${v}`)
        .join('&');
      const url = `${API_BASE}/api/games/${slug}/${categorySlug}/${filterParams ? '?' + filterParams : ''}`;
      const res = await fetch(url, { cache: 'no-store' });
      if (res.ok) {
        setData(await res.json());
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [slug, categorySlug]);

  useEffect(() => {
    fetchData(activeFilters);
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
            {listings?.length || 0} Listing{listings?.length !== 1 ? 's' : ''}
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
                    {listing.seller_name}
                    {listing.filter_display && Object.entries(listing.filter_display).map(([name, value]) => (
                      <span key={name} className="listing-row-tag">{value}</span>
                    ))}
                  </div>
                </div>
                <div className="listing-row-price">PKR {listing.price}</div>
              </Link>
            ))}
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

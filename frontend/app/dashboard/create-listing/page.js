'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { createListing } from '@/lib/api';
import { API_BASE } from '@/lib/config';

export default function CreateListingPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [games, setGames] = useState([]);
  const [selectedGame, setSelectedGame] = useState(null);
  const [categories, setCategories] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [filters, setFilters] = useState([]);
  const [filterValues, setFilterValues] = useState({});
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [price, setPrice] = useState('');
  const [quantity, setQuantity] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.push('/login');
  }, [user, loading, router]);

  // Fetch games
  useEffect(() => {
    fetch(`${API_BASE}/api/games/`)
      .then(r => r.json())
      .then(setGames)
      .catch(() => {});
  }, []);

  // Fetch categories when game is selected
  useEffect(() => {
    if (selectedGame) {
      fetch(`${API_BASE}/api/games/${selectedGame.slug}/`)
        .then(r => r.json())
        .then(data => {
          setCategories(data.categories || []);
          setSelectedCategory(null);
          setFilters([]);
          setFilterValues({});
        })
        .catch(() => {});
    }
  }, [selectedGame]);

  // Fetch filters when category is selected
  useEffect(() => {
    if (selectedGame && selectedCategory) {
      fetch(`${API_BASE}/api/games/${selectedGame.slug}/${selectedCategory.slug}/`)
        .then(r => r.json())
        .then(data => {
          setFilters(data.filters || []);
          setFilterValues({});
        })
        .catch(() => {});
    }
  }, [selectedGame, selectedCategory]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const listingData = {
        game_slug: selectedGame.slug,
        category_slug: selectedCategory.slug,
        title,
        description,
        price: parseFloat(price),
        filter_values: filterValues,
      };
      // Only include quantity if the seller set it
      if (quantity !== '') {
        listingData.quantity = parseInt(quantity);
      }
      await createListing(listingData);
      router.push('/dashboard');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
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
        <div className="breadcrumb">
          <a href="/dashboard">Dashboard</a>
          <span className="breadcrumb-sep">›</span>
          <span>Create Listing</span>
        </div>
        <h1 className="page-title">Create New Listing</h1>
      </div>

      <div className="form-card">
        {error && <div className="alert alert-error">{error}</div>}

        <form onSubmit={handleSubmit}>
          {/* Step 1: Select Game */}
          <div className="form-group">
            <label className="form-label">Game</label>
            <select
              className="form-input"
              value={selectedGame?.slug || ''}
              onChange={(e) => {
                const game = games.find(g => g.slug === e.target.value);
                setSelectedGame(game || null);
              }}
              required
            >
              <option value="">Select a game</option>
              {games.map(g => (
                <option key={g.id} value={g.slug}>{g.name}</option>
              ))}
            </select>
          </div>

          {/* Step 2: Select Category */}
          {selectedGame && (
            <div className="form-group">
              <label className="form-label">Category</label>
              <select
                className="form-input"
                value={selectedCategory?.slug || ''}
                onChange={(e) => {
                  const gc = categories.find(c => c.category.slug === e.target.value);
                  setSelectedCategory(gc?.category || null);
                }}
                required
              >
                <option value="">Select a category</option>
                {categories.map(gc => (
                  <option key={gc.id} value={gc.category.slug}>
                    {gc.category.icon} {gc.category.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Step 3: Dynamic Filters */}
          {filters.length > 0 && (
            <div className="form-section">
              <h3 className="form-section-title">Filter Values</h3>
              {filters.map(filter => (
                <div key={filter.id} className="form-group">
                  <label className="form-label">{filter.name}</label>
                  {filter.filter_type === 'button' ? (
                    <div className="filter-chips">
                      {filter.options.map(opt => (
                        <button
                          type="button"
                          key={opt.id}
                          className={`filter-chip ${filterValues[filter.id] === opt.value ? 'active' : ''}`}
                          onClick={() => setFilterValues({
                            ...filterValues,
                            [filter.id]: filterValues[filter.id] === opt.value ? undefined : opt.value,
                          })}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <select
                      className="form-input"
                      value={filterValues[filter.id] || ''}
                      onChange={(e) => setFilterValues({
                        ...filterValues,
                        [filter.id]: e.target.value || undefined,
                      })}
                    >
                      <option value="">Select {filter.name}</option>
                      {filter.options.map(opt => (
                        <option key={opt.id} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Step 4: Listing Details */}
          {selectedCategory && (
            <>
              <div className="form-group">
                <label className="form-label">Title</label>
                <input
                  type="text"
                  className="form-input"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g., Valorant Account — Diamond Rank, 50+ Skins"
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label">Description</label>
                <textarea
                  className="form-textarea"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Describe what you're selling..."
                  rows={4}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Price (PKR)</label>
                <input
                  type="number"
                  className="form-input"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  placeholder="e.g., 5000"
                  min="1"
                  step="1"
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label">Stock Quantity (Optional)</label>
                <input
                  type="number"
                  className="form-input"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  placeholder="Leave empty for unlimited"
                  min="1"
                  step="1"
                />
                <span className="form-hint">
                  Leave empty for an evergreen listing that never goes out of stock.
                  Set a number to auto-deactivate after that many sales.
                </span>
              </div>

              <button type="submit" className="btn btn-primary btn-full" disabled={submitting}>
                {submitting ? 'Creating...' : 'Create Listing'}
              </button>
            </>
          )}
        </form>
      </div>
    </div>
  );
}

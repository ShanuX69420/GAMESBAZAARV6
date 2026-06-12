'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { createListing } from '@/lib/api';
import { API_BASE } from '@/lib/config';
import { isFilterVisible, pruneHiddenFilterValues } from '@/lib/filterDependencies';

export default function CreateListingPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [games, setGames] = useState([]);
  const [selectedGame, setSelectedGame] = useState(null);
  const [categories, setCategories] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [allowAutoDelivery, setAllowAutoDelivery] = useState(false);
  const [listingMode, setListingMode] = useState('standard');
  const [options, setOptions] = useState([]);
  const [selectedOptionId, setSelectedOptionId] = useState('');
  const [filters, setFilters] = useState([]);
  const [filterValues, setFilterValues] = useState({});
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [price, setPrice] = useState('');
  const [quantity, setQuantity] = useState('');
  const [deliveryTime, setDeliveryTime] = useState('1-2 Hours');
  const [isAutoDelivery, setIsAutoDelivery] = useState(false);
  const [autoDeliveryData, setAutoDeliveryData] = useState('');
  const [deliveryInstructions, setDeliveryInstructions] = useState('');
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
          setAllowAutoDelivery(false);
          setListingMode('standard');
          setOptions([]);
          setSelectedOptionId('');
          setFilters([]);
          setFilterValues({});
          setIsAutoDelivery(false);
          setAutoDeliveryData('');
        })
        .catch(() => {});
    }
  }, [selectedGame]);

  // Fetch filters + auto delivery permission when category is selected
  useEffect(() => {
    if (selectedGame && selectedCategory) {
      fetch(`${API_BASE}/api/games/${selectedGame.slug}/${selectedCategory.slug}/`)
        .then(r => r.json())
        .then(data => {
          setFilters(data.filters || []);
          setFilterValues({});
          setAllowAutoDelivery(data.allow_auto_delivery || false);
          setListingMode(data.listing_mode || 'standard');
          setOptions(data.options || []);
          setSelectedOptionId('');
          // Reset auto delivery if not allowed
          if (!data.allow_auto_delivery) {
            setIsAutoDelivery(false);
            setAutoDeliveryData('');
          }
        })
        .catch(() => {});
    }
  }, [selectedGame, selectedCategory]);

  // When toggling auto delivery, adjust delivery time
  useEffect(() => {
    if (isAutoDelivery) {
      setDeliveryTime('Instant');
    } else {
      setDeliveryTime('1-2 Hours');
    }
  }, [isAutoDelivery]);

  function hasFilterValue(filter) {
    const value = filterValues[filter.id];
    return typeof value === 'string' ? value.trim() !== '' : value !== undefined && value !== null;
  }

  // Changing a parent filter can hide dependent filters — drop their values too.
  function updateFilterValue(filterId, value) {
    setFilterValues(prev => pruneHiddenFilterValues(filters, { ...prev, [filterId]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');

    if (!selectedGame || !selectedCategory) {
      setError('Please select a game and category.');
      return;
    }

    const isOfferMode = listingMode === 'offer';
    if (isOfferMode && !selectedOptionId) {
      setError('Please choose an option to make an offer for.');
      return;
    }
    if (isOfferMode && !deliveryInstructions.trim()) {
      setError('Please add delivery instructions so buyers know what you need from them.');
      return;
    }

    const missingFilters = filters.filter(
      filter => isFilterVisible(filter, filterValues) && !hasFilterValue(filter)
    );
    if (missingFilters.length > 0) {
      setError(`Please select all required filters: ${missingFilters.map(filter => filter.name).join(', ')}.`);
      return;
    }

    setSubmitting(true);
    try {
      const listingData = {
        game_slug: selectedGame.slug,
        category_slug: selectedCategory.slug,
        title: isOfferMode ? '' : title,
        description: isOfferMode ? '' : description,
        price: parseFloat(price),
        delivery_time: isAutoDelivery ? 'Instant' : deliveryTime,
        filter_values: filterValues,
        is_auto_delivery: isAutoDelivery,
        auto_delivery_data: isAutoDelivery ? autoDeliveryData : '',
        delivery_instructions: deliveryInstructions,
      };
      if (isOfferMode) {
        listingData.option_id = parseInt(selectedOptionId);
      }
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

          {/* Step 3: Dynamic Filters (dependent filters appear once their parent is picked) */}
          {filters.length > 0 && (
            <div className="form-section">
              <h3 className="form-section-title">Filter Values</h3>
              {filters.filter(filter => isFilterVisible(filter, filterValues)).map(filter => (
                <div key={filter.id} className="form-group">
                  <label className="form-label">{filter.name}</label>
                  {filter.filter_type === 'button' ? (
                    <div className="filter-chips">
                      {filter.options.map(opt => (
                        <button
                          type="button"
                          key={opt.id}
                          className={`filter-chip ${filterValues[filter.id] === opt.value ? 'active' : ''}`}
                          onClick={() => updateFilterValue(
                            filter.id,
                            filterValues[filter.id] === opt.value ? undefined : opt.value,
                          )}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <select
                      className="form-input"
                      value={filterValues[filter.id] || ''}
                      onChange={(e) => updateFilterValue(filter.id, e.target.value || undefined)}
                      required
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
              {listingMode === 'offer' ? (
                <div className="form-group">
                  <label className="form-label">Option</label>
                  {options.length > 0 ? (
                    <>
                      <select
                        className="form-input"
                        value={selectedOptionId}
                        onChange={(e) => setSelectedOptionId(e.target.value)}
                        required
                      >
                        <option value="">Select an option</option>
                        {options.map(opt => (
                          <option key={opt.id} value={opt.id}>
                            {opt.name}
                            {opt.min_price ? ` — lowest offer PKR ${Number(opt.min_price).toLocaleString()}` : ''}
                          </option>
                        ))}
                      </select>
                      <span className="form-hint">
                        Your offer will appear under this option, competing with other sellers
                        on price and delivery time. The listing title is set automatically.
                      </span>
                    </>
                  ) : (
                    <span className="form-hint">
                      No options have been set up for this category yet. Please contact support.
                    </span>
                  )}
                </div>
              ) : (
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
                </>
              )}

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

              {/* Stock Quantity — hidden for auto delivery */}
              {!isAutoDelivery && (
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
              )}

              {/* Auto Delivery Toggle */}
              {allowAutoDelivery && (
                <div className="form-group">
                  <div className="auto-delivery-toggle-wrap">
                    <label className="auto-delivery-toggle" htmlFor="auto-delivery-toggle">
                      <input
                        type="checkbox"
                        id="auto-delivery-toggle"
                        checked={isAutoDelivery}
                        onChange={(e) => setIsAutoDelivery(e.target.checked)}
                      />
                      <span className="auto-delivery-toggle-slider"></span>
                      <span className="auto-delivery-toggle-label">
                        <svg className="auto-delivery-flash" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
                          <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z"/>
                        </svg>
                        Automated Delivery
                      </span>
                    </label>
                    <span className="form-hint" style={{ marginTop: '6px' }}>
                      Enable to automatically deliver digital content to buyers upon purchase.
                      Delivery time is set to Instant.
                    </span>
                  </div>
                </div>
              )}

              {/* Auto Delivery Data */}
              {isAutoDelivery && (
                <div className="form-group">
                  <label className="form-label">
                    <svg className="auto-delivery-flash" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" style={{ marginRight: '6px', verticalAlign: '-2px' }}>
                      <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z"/>
                    </svg>
                    Delivery Content
                    {autoDeliveryData.trim() && (
                      <span className="auto-delivery-count">
                        — {autoDeliveryData.split('\n').filter(l => l.trim()).length} item{autoDeliveryData.split('\n').filter(l => l.trim()).length !== 1 ? 's' : ''}
                      </span>
                    )}
                  </label>
                  <textarea
                    className="form-textarea"
                    value={autoDeliveryData}
                    onChange={(e) => setAutoDeliveryData(e.target.value)}
                    placeholder={"Enter one item per line. Each line = 1 stock unit.\n\nExample:\nuser1@email.com:password123\nuser2@email.com:password456\nACTIVATION-KEY-XXXX-YYYY"}
                    rows={8}
                    required
                  />
                  <span className="form-hint" style={{ color: '#D97706' }}>
                    ⚡ Each line = 1 stock item. Stock quantity is set automatically. Items are delivered one per purchase.
                  </span>
                </div>
              )}

              {/* Delivery Time (hidden when auto delivery is on) */}
              {!isAutoDelivery && (
                <div className="form-group">
                  <label className="form-label">Delivery Time</label>
                  <select
                    className="form-input"
                    value={deliveryTime}
                    onChange={(e) => setDeliveryTime(e.target.value)}
                  >
                    <option value="1-2 Hours">1-2 Hours</option>
                    <option value="2-6 Hours">2-6 Hours</option>
                    <option value="6-12 Hours">6-12 Hours</option>
                    <option value="12-24 Hours">12-24 Hours</option>
                    <option value="1-3 Days">1-3 Days</option>
                  </select>
                </div>
              )}

              {/* Delivery Instructions (required for offer-mode categories) */}
              <div className="form-group">
                <label className="form-label">
                  Delivery Instructions {listingMode === 'offer' ? '' : '(Optional)'}
                </label>
                <textarea
                  className="form-textarea"
                  value={deliveryInstructions}
                  onChange={(e) => setDeliveryInstructions(e.target.value)}
                  placeholder={listingMode === 'offer'
                    ? "Tell buyers what you need and how delivery works, e.g., 'Only your Player ID / UID is required. No password needed. Double-check your UID before ordering.'"
                    : "Optional note shown to buyers, e.g., 'Please change the password immediately after receiving the account'"}
                  rows={3}
                  required={listingMode === 'offer'}
                />
                <span className="form-hint">
                  {listingMode === 'offer'
                    ? 'Required — buyers see this next to your offer before purchasing.'
                    : 'This note will be visible to every buyer when they purchase.'}
                </span>
              </div>

              <button type="submit" className="btn btn-primary btn-full" disabled={submitting || (listingMode === 'offer' && options.length === 0)}>
                {submitting ? 'Creating...' : isAutoDelivery ? '⚡ Create Auto-Delivery Listing' : listingMode === 'offer' ? 'Create Offer' : 'Create Listing'}
              </button>
            </>
          )}
        </form>
      </div>
    </div>
  );
}

'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import ChatBox from '@/components/ChatBox';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

export default function ListingDetailPage() {
  const params = useParams();
  const { id } = params;
  const { user } = useAuth();
  const [listing, setListing] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/api/listings/${id}/`, { cache: 'no-store' })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { setListing(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  if (!listing) {
    return (
      <div className="container">
        <div className="empty-state">
          <div className="empty-state-icon">🔍</div>
          <p>Listing not found.</p>
        </div>
      </div>
    );
  }

  const isOwnListing = user && user.id === listing.seller_id;

  return (
    <div className="container">
      <div className="page-header">
        <div className="breadcrumb">
          <a href="/">Home</a>
          <span className="breadcrumb-sep">›</span>
          <span>{listing.game_name}</span>
          <span className="breadcrumb-sep">›</span>
          <span>{listing.category_name}</span>
        </div>
      </div>

      <div className="listing-detail">
        {/* Left side: listing info */}
        <div className="listing-detail-main">
          <h1 className="listing-detail-title">{listing.title}</h1>

          {/* Filter badges */}
          {listing.filter_display && Object.keys(listing.filter_display).length > 0 && (
            <div className="listing-detail-tags">
              {Object.entries(listing.filter_display).map(([name, value]) => (
                <span key={name} className="listing-tag">
                  {name}: {value}
                </span>
              ))}
            </div>
          )}

          {listing.description && (
            <div className="listing-detail-desc">
              <h3>Description</h3>
              <p>{listing.description}</p>
            </div>
          )}
        </div>

        {/* Right side: price card + chat */}
        <div className="listing-detail-sidebar">
          <div className="listing-detail-price-card">
            <div className="listing-detail-price">PKR {listing.price}</div>
            <div className="listing-detail-seller">
              Sold by <strong>{listing.seller_name}</strong>
            </div>
            <div className="listing-detail-date">
              Listed {new Date(listing.created_at).toLocaleDateString()}
            </div>
          </div>

          {/* Chat box — like FunPay */}
          {!isOwnListing && (
            <div style={{ marginTop: '16px' }}>
              <ChatBox
                sellerId={listing.seller_id}
                sellerName={listing.seller_name}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

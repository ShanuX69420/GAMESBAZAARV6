'use client';

import { useState, useEffect, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { buyListing, getWallet } from '@/lib/api';
import ChatBox from '@/components/ChatBox';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

export default function ListingDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { id } = params;
  const { user } = useAuth();
  const [listing, setListing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [wallet, setWallet] = useState(null);
  const [quantity, setQuantity] = useState(1);
  const [buying, setBuying] = useState(false);
  const [buyError, setBuyError] = useState('');
  const [buySuccess, setBuySuccess] = useState('');
  const buyingRef = useRef(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/listings/${id}/`, { cache: 'no-store' })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { setListing(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    if (user) {
      getWallet().then(w => setWallet(w)).catch(() => {});
    }
  }, [user]);

  async function handleBuy() {
    if (buyingRef.current) return;
    buyingRef.current = true;
    setBuyError('');
    setBuySuccess('');
    setBuying(true);
    try {
      const order = await buyListing(listing.id, quantity);
      setBuySuccess(`Order #${order.id} placed! Redirecting...`);
      setTimeout(() => router.push(`/order/${order.id}`), 1500);
    } catch (err) {
      setBuyError(err.message);
      buyingRef.current = false;
      setBuying(false);
    }
  }

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
  const totalPrice = (listing.price * quantity).toFixed(2);
  const hasBalance = wallet && parseFloat(wallet.balance) >= parseFloat(totalPrice);

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

        {/* Right side: price card + buy + chat */}
        <div className="listing-detail-sidebar">
          <div className="listing-detail-price-card">
            <div className="listing-detail-price">PKR {listing.price}</div>
            <div className="listing-detail-seller">
              Sold by <strong>{listing.seller_name}</strong>
            </div>
            <div className="listing-detail-date">
              Listed {new Date(listing.created_at).toLocaleDateString()}
            </div>

            {/* Stock */}
            {listing.quantity !== null && listing.quantity > 0 && (
              <div className="listing-stock">
                📦 {listing.quantity} in stock
              </div>
            )}
            {listing.quantity === null && listing.status === 'active' && (
              <div className="listing-stock">
                ✅ Available
              </div>
            )}
            {listing.status === 'sold' && (
              <div className="listing-sold-badge">🚫 Out of Stock</div>
            )}

            {/* Buy section */}
            {!isOwnListing && listing.status === 'active' && (
              <div className="buy-section">
                {user ? (
                  <>
                    {/* Quantity selector — only show for finite stock > 1 */}
                    {listing.quantity !== null && listing.quantity > 1 && (
                      <div className="form-group" style={{ marginBottom: '12px' }}>
                        <label className="form-label">Quantity</label>
                        <div className="qty-selector">
                          <button
                            className="qty-btn"
                            onClick={() => setQuantity(Math.max(1, quantity - 1))}
                            disabled={quantity <= 1}
                          >−</button>
                          <span className="qty-value">{quantity}</span>
                          <button
                            className="qty-btn"
                            onClick={() => setQuantity(Math.min(listing.quantity, quantity + 1))}
                            disabled={quantity >= listing.quantity}
                          >+</button>
                        </div>
                      </div>
                    )}

                    {quantity > 1 && (
                      <div className="buy-total">
                        Total: <strong>PKR {totalPrice}</strong>
                      </div>
                    )}

                    {/* Wallet balance */}
                    {wallet && (
                      <div className="buy-wallet-info">
                        Wallet: <strong>PKR {Number(wallet.balance).toLocaleString('en-PK', { minimumFractionDigits: 2 })}</strong>
                        {!hasBalance && (
                          <Link href="/wallet" className="buy-topup-link">Add Funds →</Link>
                        )}
                      </div>
                    )}

                    {buyError && <div className="alert alert-error" style={{ marginTop: '8px' }}>{buyError}</div>}
                    {buySuccess && <div className="alert alert-success" style={{ marginTop: '8px' }}>{buySuccess}</div>}

                    <button
                      className="btn btn-primary btn-full buy-now-btn"
                      onClick={handleBuy}
                      disabled={buying || !hasBalance}
                    >
                      {buying ? 'Purchasing...' : `🛒 Buy Now — PKR ${totalPrice}`}
                    </button>
                  </>
                ) : (
                  <Link href="/login" className="btn btn-primary btn-full buy-now-btn">
                    Log in to Buy
                  </Link>
                )}
              </div>
            )}
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


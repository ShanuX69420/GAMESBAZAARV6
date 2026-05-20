'use client';

import { useState, useEffect, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { buyListing, getWallet } from '@/lib/api';
import { API_BASE } from '@/lib/config';
import { orderLabel, orderPath } from '@/lib/orderNumbers';
import ChatBox from '@/components/ChatBox';
import ReportModal from '@/components/ReportModal';

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
  const [showReport, setShowReport] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

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

  function openConfirmModal() {
    setBuyError('');
    setBuySuccess('');
    setShowConfirm(true);
  }

  async function handleBuy() {
    if (buyingRef.current) return;
    buyingRef.current = true;
    setBuyError('');
    setBuySuccess('');
    setBuying(true);
    try {
      const order = await buyListing(listing.id, quantity);
      setShowConfirm(false);
      setBuySuccess(`Order ${orderLabel(order)} placed! Redirecting...`);
      setTimeout(() => router.push(orderPath(order)), 1500);
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
              <h2>Description</h2>
              <p>{listing.description}</p>
            </div>
          )}

        </div>

        {/* Right side: price card + buy + chat */}
        <div className="listing-detail-sidebar">
          {/* Buyer Protection Badge */}
          {listing.buyer_protection_enabled && (
            <div className="buyer-protection-badge">
              <div className="buyer-protection-badge-left">
                <svg className="buyer-protection-badge-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                  <polyline points="9 12 11 14 15 10"/>
                </svg>
                <span>Buyer Protection</span>
              </div>
              <span className="buyer-protection-badge-days">14 Day</span>
            </div>
          )}

          <div className="listing-detail-price-card">
            <div className="listing-detail-price">PKR {listing.price}</div>
            <div className="listing-detail-seller">
              Sold by <Link href={`/seller/${listing.seller_name}`} style={{ color: 'var(--green-600)', fontWeight: 600 }}>{listing.seller_name}</Link>
            </div>
            <div className="listing-detail-date">
              Listed {new Date(listing.created_at).toLocaleDateString()}
            </div>

            {/* Delivery Time */}
            {listing.is_auto_delivery ? (
              <div className="instant-delivery-badge">
                <svg className="instant-delivery-icon" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
                  <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z"/>
                </svg>
                Instant Delivery
              </div>
            ) : listing.delivery_time && (
              <div className="listing-delivery-time">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"/>
                  <polyline points="12 6 12 12 16 14"/>
                </svg>
                {listing.delivery_time}
              </div>
            )}

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
                      onClick={openConfirmModal}
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

          {/* Report button */}
          {!isOwnListing && user && (
            <div style={{ marginTop: '12px', display: 'flex', justifyContent: 'center' }}>
              <button
                className="report-flag-btn"
                onClick={() => setShowReport(true)}
                title="Report this listing"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/>
                  <line x1="4" y1="22" x2="4" y2="15"/>
                </svg>
                Report
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Report Modal */}
      <ReportModal
        isOpen={showReport}
        onClose={() => setShowReport(false)}
        targetType="listing"
        listingId={listing.id}
        targetName={listing.title}
      />

      {/* Order Confirmation Modal */}
      {showConfirm && (
        <div className="confirm-order-overlay" onClick={() => !buying && setShowConfirm(false)}>
          <div className="confirm-order-modal" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-order-header">
              <div className="confirm-order-header-left">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/>
                  <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>
                </svg>
                <h2>Confirm Your Order</h2>
              </div>
              <button className="confirm-order-close" onClick={() => !buying && setShowConfirm(false)} aria-label="Close">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>

            <div className="confirm-order-body">
              {/* Item info */}
              <div className="confirm-order-item">
                <div className="confirm-order-item-name">{listing.title}</div>
                <div className="confirm-order-item-meta">
                  {listing.game_name} · {listing.category_name}
                </div>
              </div>

              {/* Order summary rows */}
              <div className="confirm-order-summary">
                <div className="confirm-order-row">
                  <span className="confirm-order-label">Seller</span>
                  <span className="confirm-order-value">{listing.seller_name}</span>
                </div>
                <div className="confirm-order-row">
                  <span className="confirm-order-label">Unit Price</span>
                  <span className="confirm-order-value">PKR {Number(listing.price).toLocaleString('en-PK', { minimumFractionDigits: 2 })}</span>
                </div>
                {quantity > 1 && (
                  <div className="confirm-order-row">
                    <span className="confirm-order-label">Quantity</span>
                    <span className="confirm-order-value">×{quantity}</span>
                  </div>
                )}
                <div className="confirm-order-row confirm-order-row-total">
                  <span className="confirm-order-label">Total</span>
                  <span className="confirm-order-value confirm-order-total">PKR {Number(totalPrice).toLocaleString('en-PK', { minimumFractionDigits: 2 })}</span>
                </div>
              </div>

              {/* Wallet info */}
              {wallet && (
                <div className="confirm-order-wallet">
                  <div className="confirm-order-row">
                    <span className="confirm-order-label">Wallet Balance</span>
                    <span className="confirm-order-value">PKR {Number(wallet.balance).toLocaleString('en-PK', { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="confirm-order-row">
                    <span className="confirm-order-label">After Purchase</span>
                    <span className="confirm-order-value" style={{ color: 'var(--green-600)', fontWeight: 600 }}>
                      PKR {(parseFloat(wallet.balance) - parseFloat(totalPrice)).toLocaleString('en-PK', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                </div>
              )}

              {listing.is_auto_delivery && (
                <div className="confirm-order-notice confirm-order-notice-instant">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z"/>
                  </svg>
                  This item will be delivered instantly after purchase.
                </div>
              )}

              <div className="confirm-order-notice">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                </svg>
                Your payment is protected — the seller only receives it after you confirm delivery.
              </div>

              {buyError && <div className="alert alert-error" style={{ margin: '0' }}>{buyError}</div>}
            </div>

            <div className="confirm-order-actions">
              <button className="btn btn-outline" onClick={() => setShowConfirm(false)} disabled={buying}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleBuy} disabled={buying}>
                {buying ? (
                  <><div className="loading-spinner" style={{ width: '16px', height: '16px', borderWidth: '2px' }}></div> Processing...</>
                ) : (
                  `✅ Confirm Purchase — PKR ${Number(totalPrice).toLocaleString('en-PK', { minimumFractionDigits: 2 })}`
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

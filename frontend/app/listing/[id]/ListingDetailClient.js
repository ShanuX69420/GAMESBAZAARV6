'use client';

import { useState, useEffect, useRef } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import {
  buyListing, getWallet, getSellerReviews,
  initiateJazzCashPurchase, pollJazzCashPayment, validateTopupId,
} from '@/lib/api';
import { API_BASE } from '@/lib/config';
import { trackBeginCheckout, trackPurchase, trackViewListing } from '@/lib/analytics';
import { orderLabel, orderPath } from '@/lib/orderNumbers';
import ChatBox from '@/components/ChatBox';
import ReportModal from '@/components/ReportModal';

const LISTING_REVIEW_PAGE_SIZE = 5;
const JAZZCASH_MOBILE_REGEX = /^03\d{9}$/;
// Keep in sync with JAZZCASH_MIN_PAYMENT_PKR (backend settings).
const MIN_JAZZCASH_PAYMENT = 20;

const formatPKR = (n) => Number(n).toLocaleString('en-PK', { minimumFractionDigits: 2 });
// Per-unit prices can be tiny (e.g., PKR 1.4 / M) — keep up to 2 decimals.
const formatUnitPrice = (n) => Number(n).toLocaleString('en-PK', { maximumFractionDigits: 2 });
const formatAmount = (n) => Number(n).toLocaleString('en-PK');

export default function ListingDetailClient({ initialListing = null }) {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { id } = params;
  const { user } = useAuth();
  const [listing, setListing] = useState(initialListing);
  const [loading, setLoading] = useState(!initialListing);
  const [wallet, setWallet] = useState(null);
  const [walletFetched, setWalletFetched] = useState(false);
  const autoBuyRef = useRef(false);
  const [quantity, setQuantity] = useState(1);
  const [qtyInput, setQtyInput] = useState('1');
  const [buying, setBuying] = useState(false);
  const [buyError, setBuyError] = useState('');
  const [buySuccess, setBuySuccess] = useState('');
  const [jazzCashMobile, setJazzCashMobile] = useState('');
  const buyingRef = useRef(false);
  const [showReport, setShowReport] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  // Auto-fulfilled top-ups: buyer's player/user ID entered at checkout.
  const [checkoutFieldValues, setCheckoutFieldValues] = useState({});
  const [idVerify, setIdVerify] = useState({ status: 'idle', name: '' });
  const [reviews, setReviews] = useState([]);
  const [reviewPagination, setReviewPagination] = useState(null);
  const [loadingReviews, setLoadingReviews] = useState(false);
  const [loadingMoreReviews, setLoadingMoreReviews] = useState(false);
  const reviewRequestRef = useRef(0);

  useEffect(() => {
    if (initialListing) {
      setListing(initialListing);
      setLoading(false);
      return;
    }
    fetch(`${API_BASE}/api/listings/${id}/`, { cache: 'no-store' })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { setListing(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [id, initialListing]);

  useEffect(() => {
    if (user) {
      getWallet()
        .then(w => setWallet(w))
        .catch(() => {})
        .finally(() => setWalletFetched(true));
    }
  }, [user]);

  // Ads funnel: one view_item / ViewContent per listing viewed.
  useEffect(() => {
    if (listing) trackViewListing(listing);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listing?.id]);

  // Currency listings: start at the seller's minimum (or the amount picked on
  // the browse page via ?qty=), clamped to the available stock.
  useEffect(() => {
    if (!listing || listing.listing_mode !== 'currency') return;
    const minQ = listing.min_quantity || 1;
    const stock = listing.quantity ?? null;
    const fromUrl = parseInt(searchParams.get('qty') || '', 10);
    let q = Number.isFinite(fromUrl) ? fromUrl : minQ;
    q = Math.max(minQ, q);
    if (stock !== null) q = Math.min(q, stock);
    setQuantity(q);
    setQtyInput(String(q));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listing?.id]);

  // Coming from an offer page with ?buy=1: jump straight into the purchase
  // confirmation once the listing and wallet are ready.
  useEffect(() => {
    if (autoBuyRef.current) return;
    if (searchParams.get('buy') !== '1') return;
    if (!user || !walletFetched || !listing) return;
    if (listing.status !== 'active' || user.id === listing.seller_id) return;
    autoBuyRef.current = true;
    openConfirmModal();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, walletFetched, listing, searchParams]);

  // Load seller reviews
  useEffect(() => {
    const sellerName = listing?.seller_name;
    const requestId = reviewRequestRef.current + 1;
    reviewRequestRef.current = requestId;

    if (!sellerName) {
      setReviews([]);
      setReviewPagination(null);
      setLoadingReviews(false);
      return;
    }

    let cancelled = false;
    const controller = new AbortController();

    setLoadingReviews(true);
    getSellerReviews(sellerName, { limit: LISTING_REVIEW_PAGE_SIZE }, { signal: controller.signal })
      .then(data => {
        if (cancelled || reviewRequestRef.current !== requestId) return;
        setReviews(data.reviews || []);
        setReviewPagination(data.pagination || null);
      })
      .catch((err) => {
        if (err?.name === 'AbortError' || cancelled || reviewRequestRef.current !== requestId) return;
        setReviews([]);
        setReviewPagination(null);
      })
      .finally(() => {
        if (!cancelled && reviewRequestRef.current === requestId) {
          setLoadingReviews(false);
        }
      });

    return () => {
      cancelled = true;
      controller.abort();
      if (reviewRequestRef.current === requestId) {
        reviewRequestRef.current += 1;
      }
    };
  }, [listing?.seller_name]);

  async function loadMoreReviews() {
    const sellerName = listing?.seller_name;
    const nextOffset = reviewPagination?.next_offset;
    const requestId = reviewRequestRef.current;

    if (!sellerName || nextOffset === null || nextOffset === undefined || loadingMoreReviews) return;

    setLoadingMoreReviews(true);
    try {
      const data = await getSellerReviews(sellerName, {
        limit: LISTING_REVIEW_PAGE_SIZE,
        offset: nextOffset,
      });
      if (reviewRequestRef.current !== requestId) return;
      setReviews(prev => [...prev, ...(data.reviews || [])]);
      setReviewPagination(data.pagination || null);
    } catch {}
    finally {
      if (reviewRequestRef.current === requestId) {
        setLoadingMoreReviews(false);
      }
    }
  }

  function renderStars(rating) {
    return '★'.repeat(Math.round(rating)) + '☆'.repeat(5 - Math.round(rating));
  }

  function openConfirmModal() {
    setBuyError('');
    setBuySuccess('');
    setIdVerify({ status: 'idle', name: '' });
    setShowConfirm(true);
    trackBeginCheckout(listing, quantity);
  }

  async function handleVerifyTopupId() {
    setIdVerify({ status: 'checking', name: '' });
    try {
      const result = await validateTopupId(listing.id, checkoutFieldValues);
      if (result.valid) {
        setIdVerify({
          status: result.unverified ? 'unverified' : 'ok',
          name: result.player_name || '',
        });
      } else {
        setIdVerify({ status: 'bad', name: '' });
      }
    } catch {
      setIdVerify({ status: 'unverified', name: '' });
    }
  }

  async function handleBuy() {
    if (buyingRef.current) return;
    buyingRef.current = true;
    setBuyError('');
    setBuySuccess('');
    setBuying(true);
    try {
      const order = await buyListing(listing.id, quantity, checkoutFieldValues);
      trackPurchase(order, listing, quantity);
      setShowConfirm(false);
      setBuySuccess(`Order ${orderLabel(order)} placed! Redirecting...`);
      setTimeout(() => router.push(orderPath(order)), 1500);
    } catch (err) {
      setBuyError(err.message);
      buyingRef.current = false;
      setBuying(false);
    }
  }

  async function handleJazzCashBuy() {
    if (buyingRef.current) return;
    const mobile = jazzCashMobile.trim();
    if (!JAZZCASH_MOBILE_REGEX.test(mobile)) {
      setBuyError('Enter a valid JazzCash mobile number (e.g., 03001234567).');
      return;
    }
    buyingRef.current = true;
    setBuyError('');
    setBuySuccess('');
    setBuying(true);
    try {
      let payment = await initiateJazzCashPurchase(listing.id, quantity, mobile, checkoutFieldValues);
      if (payment.status === 'pending') {
        payment = await pollJazzCashPayment(payment.id);
      }
      if (payment?.status === 'completed' && payment.order_id) {
        const order = { id: payment.order_id, order_number: payment.order_number };
        trackPurchase(order, listing, quantity);
        setShowConfirm(false);
        setBuySuccess(`Order ${orderLabel(order)} placed! Redirecting...`);
        // Keep `buying` true so the buy button stays disabled until redirect.
        setTimeout(() => router.push(orderPath(order)), 1500);
        return;
      }
      if (payment?.status === 'completed') {
        // Paid, but the listing was no longer available — money is in the wallet.
        setShowConfirm(false);
        setBuyError(payment.note || 'Your payment was received but the purchase could not be completed. The amount was added to your wallet.');
        getWallet().then(w => setWallet(w)).catch(() => {});
      } else if (payment?.status === 'failed') {
        setBuyError(payment.user_message || 'JazzCash payment failed. Please try again.');
      } else {
        setBuyError('Your JazzCash payment is still processing. Once it is confirmed, your order will appear in My Orders automatically.');
      }
    } catch (err) {
      setBuyError(err.message);
    }
    buyingRef.current = false;
    setBuying(false);
  }

  function handleConfirmPurchase() {
    const canPayFromWallet = wallet && parseFloat(wallet.balance) >= listing.price * quantity;
    if (canPayFromWallet) {
      handleBuy();
    } else {
      handleJazzCashBuy();
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
          <p>Listing not found.</p>
        </div>
      </div>
    );
  }

  const isOwnListing = user && user.id === listing.seller_id;
  const isCurrency = listing.listing_mode === 'currency';
  const unitName = listing.unit_name || '';
  const minQty = listing.min_quantity || 1;
  const stock = listing.quantity ?? null;
  const parsedQtyInput = parseInt(qtyInput, 10);
  const currencyQtyValid = !isCurrency || (
    Number.isFinite(parsedQtyInput)
    && parsedQtyInput >= minQty
    && (stock === null || parsedQtyInput <= stock)
  );

  function handleCurrencyQtyChange(value) {
    setQtyInput(value);
    const parsed = parseInt(value, 10);
    if (Number.isFinite(parsed) && parsed >= minQty && (stock === null || parsed <= stock)) {
      setQuantity(parsed);
    }
  }

  function stepCurrencyQty(delta) {
    let next = quantity + delta;
    next = Math.max(minQty, next);
    if (stock !== null) next = Math.min(stock, next);
    setQuantity(next);
    setQtyInput(String(next));
  }

  const totalPrice = (listing.price * quantity).toFixed(2);
  const walletBalance = wallet ? parseFloat(wallet.balance) : 0;
  const hasBalance = wallet && walletBalance >= parseFloat(totalPrice);
  const jazzCashEnabled = Boolean(wallet?.jazzcash_enabled);
  const canBuy = hasBalance || jazzCashEnabled;
  const isInstant = listing.is_auto_delivery || listing.instant_delivery;
  const requiredCheckoutFields = listing.required_checkout_fields || [];
  const checkoutFieldsFilled = requiredCheckoutFields.every(
    (f) => (checkoutFieldValues[f.key] || '').trim()
  );
  // JazzCash only covers what the wallet is missing, subject to the gateway's
  // minimum charge — anything above the shortfall lands back in the wallet.
  const payWithJazzCash = !hasBalance && jazzCashEnabled;
  const walletApplied = Math.min(walletBalance, parseFloat(totalPrice));
  const jazzCashShortfall = Math.max(0, parseFloat(totalPrice) - walletBalance);
  const jazzCashCharge = Math.max(jazzCashShortfall, MIN_JAZZCASH_PAYMENT);
  const jazzCashChange = jazzCashCharge - jazzCashShortfall;
  // The initiate endpoint answers "pending" right away and we poll while the
  // buyer approves on their phone, so the prompt has to show for the whole
  // buying window — initiation and polling both.
  const jazzCashInFlight = payWithJazzCash && buying;

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

          {/* Shown pre-purchase for offer/currency listings (UC, coins, etc.);
              standard listings reveal instructions after ordering. */}
          {(listing.option_id || isCurrency) && listing.delivery_instructions && (
            <div className="listing-detail-desc">
              <h2>Delivery Instructions</h2>
              <p style={{ whiteSpace: 'pre-line', overflowWrap: 'anywhere' }}>{listing.delivery_instructions}</p>
            </div>
          )}

        </div>

        {/* Right side: price card + buy */}
        <div className="listing-detail-sidebar">
          <div className="listing-detail-sidebar-sticky">
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
              <div className="listing-detail-price">
                PKR {isCurrency ? formatUnitPrice(listing.price) : listing.price}
                {isCurrency && unitName && <span className="currency-unit-suffix"> / {unitName}</span>}
              </div>
              <div className="listing-detail-seller">
                Sold by <Link href={`/seller/${listing.seller_name}`} style={{ color: 'var(--green-600)', fontWeight: 600 }}>{listing.seller_name}</Link>
              </div>
              <div className="listing-detail-date">
                Listed {new Date(listing.created_at).toLocaleDateString()}
              </div>

              {/* Delivery Time */}
              {isInstant ? (
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
                  {isCurrency ? `${formatAmount(listing.quantity)} ${unitName}`.trim() : listing.quantity} in stock
                </div>
              )}
              {isCurrency && (
                <div className="listing-stock">
                  Min. purchase: {formatAmount(minQty)} {unitName}
                </div>
              )}
              {listing.quantity === null && listing.status === 'active' && (
                <div className="listing-stock">
                  Available
                </div>
              )}
              {listing.status === 'sold' && (
                <div className="listing-sold-badge">Out of Stock</div>
              )}

              {/* Buy section */}
              {!isOwnListing && listing.status === 'active' && (
                <div className="buy-section">
                  {user ? (
                    <>
                      {/* Quantity selector — currency mode gets a free-amount
                          input; other listings step within finite stock */}
                      {isCurrency ? (
                        <div className="form-group" style={{ marginBottom: '12px' }}>
                          <label className="form-label">Amount{unitName ? ` (${unitName})` : ''}</label>
                          <div className="currency-qty-box">
                            <button
                              type="button"
                              className="currency-qty-btn"
                              aria-label="Decrease amount"
                              onClick={() => stepCurrencyQty(-1)}
                              disabled={quantity <= minQty}
                            >−</button>
                            <div className="currency-qty-input-wrap">
                              <input
                                type="number"
                                className="currency-qty-input"
                                inputMode="numeric"
                                min={minQty}
                                max={stock ?? undefined}
                                value={qtyInput}
                                onChange={(e) => handleCurrencyQtyChange(e.target.value)}
                                aria-label={`Amount${unitName ? ` in ${unitName}` : ''}`}
                              />
                              {unitName && <span className="currency-qty-unit">{unitName}</span>}
                            </div>
                            <button
                              type="button"
                              className="currency-qty-btn"
                              aria-label="Increase amount"
                              onClick={() => stepCurrencyQty(1)}
                              disabled={stock !== null && quantity >= stock}
                            >+</button>
                          </div>
                          {!currencyQtyValid && qtyInput !== '' && (
                            <span className="currency-qty-error" style={{ marginTop: '6px', display: 'block' }}>
                              {!Number.isFinite(parsedQtyInput) || parsedQtyInput < minQty
                                ? `Minimum purchase is ${formatAmount(minQty)} ${unitName}.`
                                : `Only ${formatAmount(stock)} ${unitName} in stock.`}
                            </span>
                          )}
                        </div>
                      ) : listing.quantity !== null && listing.quantity > 1 && (
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

                      {(quantity > 1 || isCurrency) && (
                        <div className="buy-total">
                          Total: <strong>PKR {formatPKR(totalPrice)}</strong>
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
                        disabled={buying || !canBuy || !currencyQtyValid}
                      >
                        {buying ? 'Purchasing...' : `Buy Now — PKR ${formatPKR(totalPrice)}`}
                      </button>
                      {payWithJazzCash && (
                        <div className="form-hint" style={{ marginTop: '6px', textAlign: 'center' }}>
                          {walletApplied > 0
                            ? `Pay PKR ${formatPKR(walletApplied)} from your wallet + PKR ${formatPKR(jazzCashCharge)} via JazzCash`
                            : 'Pay directly with JazzCash — no wallet balance needed'}
                        </div>
                      )}
                    </>
                  ) : (
                    <Link href="/login" className="btn btn-primary btn-full buy-now-btn">
                      Log in to Buy
                    </Link>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Bottom Section: Reviews + Chat ──────────────────────────────── */}
      <div className="listing-detail-bottom">
        {/* Left: Seller Reviews */}
        <div className="listing-detail-reviews">
          <div className="listing-detail-reviews-header">
            <h2 className="listing-detail-reviews-title">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" style={{ color: '#F59E0B' }}>
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
              </svg>
              Seller Reviews
            </h2>
            <Link href={`/seller/${listing.seller_name}`} className="listing-detail-reviews-viewall">
              View All →
            </Link>
          </div>

          {loadingReviews ? (
            <div className="listing-detail-reviews-loading">
              <div className="loading-spinner" style={{ width: '20px', height: '20px', borderWidth: '2px' }}></div>
              <span>Loading reviews…</span>
            </div>
          ) : reviews.length === 0 ? (
            <div className="listing-detail-reviews-empty">
              <p>No reviews yet for this seller.</p>
            </div>
          ) : (
            <>
              <div className="reviews-list">
                {reviews.map((review) => (
                  <div key={review.id} className="review-card">
                    <div className="review-card-header">
                      <span className="review-card-user">Buyer</span>
                      <span className="review-card-date">
                        {new Date(review.created_at).toLocaleDateString('en-PK', {
                          day: 'numeric', month: 'short', year: 'numeric',
                        })}
                        {review.updated_at && (
                          <span className="review-edited-badge"> (edited)</span>
                        )}
                      </span>
                    </div>
                    <div className="review-card-stars">{renderStars(review.rating)}</div>
                    {review.comment && (
                      <div className="review-card-comment">{review.comment}</div>
                    )}
                    {review.listing_title && (
                      <div className="review-card-listing">Purchased: {review.listing_title}</div>
                    )}

                    {/* Seller Reply */}
                    {review.seller_reply && (
                      <div className="review-reply-block">
                        <div className="review-reply-header">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="9 17 4 12 9 7"/>
                            <path d="M20 18v-2a4 4 0 00-4-4H4"/>
                          </svg>
                          <span>Seller's Reply</span>
                          {review.seller_reply_at && (
                            <span className="review-reply-date">
                              {new Date(review.seller_reply_at).toLocaleDateString('en-PK', { day: 'numeric', month: 'short', year: 'numeric' })}
                            </span>
                          )}
                        </div>
                        <div className="review-reply-text">{review.seller_reply}</div>
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {reviewPagination?.next_offset !== null && reviewPagination?.next_offset !== undefined && (
                <button
                  type="button"
                  className="btn btn-outline btn-full"
                  onClick={loadMoreReviews}
                  disabled={loadingMoreReviews}
                  style={{ marginTop: '16px' }}
                >
                  {loadingMoreReviews ? 'Loading...' : 'Load More Reviews'}
                </button>
              )}
            </>
          )}
        </div>

        {/* Right: Chat + Report */}
        <div className="listing-detail-chat-col">
          <div className="listing-detail-chat-sticky">
            {!isOwnListing && (
              <ChatBox
                sellerId={listing.seller_id}
                sellerName={listing.seller_name}
                sellerAvatarUrl={listing.seller_avatar_url}
                sellerLastActive={listing.seller_last_active}
                listingId={listing.id}
                listingTitle={listing.title}
                listingPrice={listing.price}
              />
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
                  <span className="confirm-order-value">
                    {isCurrency
                      ? `PKR ${formatUnitPrice(listing.price)}${unitName ? ` / ${unitName}` : ''}`
                      : `PKR ${Number(listing.price).toLocaleString('en-PK', { minimumFractionDigits: 2 })}`}
                  </span>
                </div>
                {(quantity > 1 || isCurrency) && (
                  <div className="confirm-order-row">
                    <span className="confirm-order-label">{isCurrency ? 'Amount' : 'Quantity'}</span>
                    <span className="confirm-order-value">
                      {isCurrency ? `${formatAmount(quantity)} ${unitName}`.trim() : `×${quantity}`}
                    </span>
                  </div>
                )}
                <div className="confirm-order-row confirm-order-row-total">
                  <span className="confirm-order-label">Total</span>
                  <span className="confirm-order-value confirm-order-total">PKR {Number(totalPrice).toLocaleString('en-PK', { minimumFractionDigits: 2 })}</span>
                </div>
              </div>

              {/* Auto-fulfilled top-ups / Steam gifts: buyer info the supplier
                  needs (player ID, friend invite link). Verify only exists for
                  top-ups — the field spec turns it off elsewhere. */}
              {requiredCheckoutFields.map((field) => (
                <div className="form-group" key={field.key} style={{ marginBottom: 0 }}>
                  <label className="form-label">{field.label} *</label>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input
                      type="text"
                      className="form-input"
                      value={checkoutFieldValues[field.key] || ''}
                      onChange={(e) => {
                        setCheckoutFieldValues((prev) => ({ ...prev, [field.key]: e.target.value }));
                        setIdVerify({ status: 'idle', name: '' });
                      }}
                      placeholder={field.placeholder || field.label}
                      maxLength={100}
                      disabled={buying}
                    />
                    {field.verify !== false && (
                      <button
                        type="button"
                        className="btn btn-outline"
                        onClick={handleVerifyTopupId}
                        disabled={buying || !checkoutFieldsFilled || idVerify.status === 'checking'}
                        style={{ whiteSpace: 'nowrap' }}
                      >
                        {idVerify.status === 'checking' ? 'Checking…' : 'Verify'}
                      </button>
                    )}
                  </div>
                  {field.verify !== false && idVerify.status === 'ok' && (
                    <span className="form-hint" style={{ color: 'var(--green-600)', fontWeight: 600 }}>
                      ✓ Found{idVerify.name ? `: ${idVerify.name}` : ''}
                    </span>
                  )}
                  {field.verify !== false && idVerify.status === 'bad' && (
                    <span className="form-hint form-error-text">
                      This ID was not found — please double-check it.
                    </span>
                  )}
                  {field.verify !== false && idVerify.status === 'unverified' && (
                    <span className="form-hint">
                      Couldn't verify right now — double-check the ID before paying.
                    </span>
                  )}
                  <span className="form-hint">
                    {field.hint || 'The top-up goes directly to this account — a wrong ID cannot be reversed.'}
                  </span>
                </div>
              ))}

              {/* Wallet info / payment breakdown */}
              {wallet && (
                <div className="confirm-order-wallet">
                  <div className="confirm-order-row">
                    <span className="confirm-order-label">Wallet Balance</span>
                    <span className="confirm-order-value">PKR {formatPKR(wallet.balance)}</span>
                  </div>
                  {hasBalance ? (
                    <div className="confirm-order-row">
                      <span className="confirm-order-label">After Purchase</span>
                      <span className="confirm-order-value" style={{ color: 'var(--green-600)', fontWeight: 600 }}>
                        PKR {formatPKR(walletBalance - parseFloat(totalPrice))}
                      </span>
                    </div>
                  ) : payWithJazzCash ? (
                    <>
                      <div className="confirm-order-row">
                        <span className="confirm-order-label">From Wallet</span>
                        <span className="confirm-order-value">PKR {formatPKR(walletApplied)}</span>
                      </div>
                      <div className="confirm-order-row">
                        <span className="confirm-order-label">Via JazzCash</span>
                        <span className="confirm-order-value">PKR {formatPKR(jazzCashCharge)}</span>
                      </div>
                      {jazzCashChange > 0 && (
                        <>
                          <div className="confirm-order-row">
                            <span className="confirm-order-label">Back to Wallet</span>
                            <span className="confirm-order-value" style={{ color: 'var(--green-600)', fontWeight: 600 }}>
                              PKR {formatPKR(jazzCashChange)}
                            </span>
                          </div>
                          <div className="form-hint" style={{ marginTop: '6px' }}>
                            The minimum JazzCash payment is PKR {MIN_JAZZCASH_PAYMENT} — the extra
                            PKR {formatPKR(jazzCashChange)} stays in your wallet.
                          </div>
                        </>
                      )}
                    </>
                  ) : (
                    <div className="form-hint form-error-text" style={{ marginTop: '6px' }}>
                      Insufficient wallet balance — <Link href="/wallet" className="buy-topup-link">add funds</Link> to continue.
                    </div>
                  )}
                </div>
              )}

              {/* JazzCash payment */}
              {payWithJazzCash && (
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label">JazzCash Mobile Number *</label>
                  <input
                    type="tel"
                    className="form-input"
                    value={jazzCashMobile}
                    onChange={(e) => setJazzCashMobile(e.target.value)}
                    placeholder="03001234567"
                    maxLength={11}
                    disabled={buying}
                  />
                  <span className="form-hint">
                    PKR {formatPKR(jazzCashCharge)} will be charged to this JazzCash account.
                  </span>
                  <div className="form-hint" style={{ marginTop: '8px' }}>
                    Prefer a bank transfer? <Link href="/wallet" className="buy-topup-link">Add funds to your wallet</Link> and
                    come back to complete the purchase.
                  </div>
                  {jazzCashInFlight && (
                    <div className="alert alert-success" style={{ marginTop: '8px', marginBottom: 0 }}>
                      <strong>Approve the payment on your phone</strong>
                      <div style={{ marginTop: '4px' }}>
                        Open your JazzCash app and approve the PKR {formatPKR(jazzCashCharge)} request.
                        Keep this page open — it updates automatically once you approve.
                      </div>
                    </div>
                  )}
                </div>
              )}

              {isInstant && (
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
              <button
                className="btn btn-primary"
                onClick={handleConfirmPurchase}
                disabled={buying || (!hasBalance && !jazzCashEnabled) || !checkoutFieldsFilled}
              >
                {buying ? (
                  <><div className="loading-spinner" style={{ width: '16px', height: '16px', borderWidth: '2px' }}></div> {jazzCashInFlight ? 'Waiting for your approval...' : 'Processing...'}</>
                ) : payWithJazzCash ? (
                  `Pay with JazzCash — PKR ${formatPKR(jazzCashCharge)}`
                ) : (
                  `Confirm Purchase — PKR ${formatPKR(totalPrice)}`
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

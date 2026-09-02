'use client';

import { Fragment, useState, useEffect, useRef } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import {
  buyListing, getWallet, getSellerReviews, getCheckoutConfig,
  initiateJazzCashPurchase, initiateGuestJazzCashPurchase, pollJazzCashPayment,
} from '@/lib/api';
import { API_BASE } from '@/lib/config';
import { trackBeginCheckout, trackPurchase, trackViewListing } from '@/lib/analytics';
import { openWhatsAppChat } from '@/lib/whatsapp';
import { loginHref } from '@/lib/loginRedirect';
import { orderLabel, orderPath } from '@/lib/orderNumbers';
import { listingBreadcrumbs, listingDisplayName } from '@/lib/listingSeo';
import { listingAlternatives, listingBrowsePath, listingLifecycle } from '@/lib/listingLifecycle';
import Select from '@/components/Select';
import OfficialStoreBadge from '@/components/OfficialStoreBadge';
import ReviewPhotos from '@/components/ReviewPhotos';

const LISTING_REVIEW_PAGE_SIZE = 5;
const JAZZCASH_MOBILE_REGEX = /^03\d{9}$/;
const GUEST_EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
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
  const { user, loading: authLoading, fetchUser } = useAuth();
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
  // Guest checkout: the email the silent account is created with, plus the
  // public checkout facts (fee, JazzCash availability) guests can't read
  // from the wallet payload.
  const [guestEmail, setGuestEmail] = useState('');
  const [checkoutConfig, setCheckoutConfig] = useState(null);
  const buyingRef = useRef(false);
  const [showConfirm, setShowConfirm] = useState(false);
  // Auto-fulfilled top-ups: buyer's player/user ID entered at checkout.
  const [checkoutFieldValues, setCheckoutFieldValues] = useState({});
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
      .then(data => {
        // Same lifecycle rules as the server render (lib/listingLifecycle.js):
        // a listing that is gone for good moves the visitor to its heir.
        const { state, redirectTo } = listingLifecycle(data);
        if (state === 'gone') {
          router.replace(redirectTo);
          return;
        }
        setListing(state === 'active' || state === 'paused' ? data : null);
        setLoading(false);
      })
      .catch(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, initialListing]);

  useEffect(() => {
    if (user) {
      getWallet()
        .then(w => setWallet(w))
        .catch(() => {})
        .finally(() => setWalletFetched(true));
    } else {
      getCheckoutConfig().then(setCheckoutConfig).catch(() => {});
    }
  }, [user]);

  // Ads funnel: one view_item / ViewContent per listing viewed.
  useEffect(() => {
    if (listing) trackViewListing(listing);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listing?.id]);

  // Start at the amount already chosen elsewhere (?qty= from the browse page,
  // or from the login round-trip); currency listings otherwise open at the
  // seller's minimum. Always clamped to the available stock.
  useEffect(() => {
    if (!listing) return;
    const isCurrencyListing = listing.listing_mode === 'currency';
    const minQ = isCurrencyListing ? (listing.min_quantity || 1) : 1;
    const stock = listing.quantity ?? null;
    const fromUrl = parseInt(searchParams.get('qty') || '', 10);
    if (!isCurrencyListing && !Number.isFinite(fromUrl)) return;
    let q = Number.isFinite(fromUrl) ? fromUrl : minQ;
    q = Math.max(minQ, q);
    if (stock !== null) q = Math.min(q, stock);
    setQuantity(q);
    setQtyInput(String(q));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listing?.id]);

  // Coming from an offer page or the login round-trip with ?buy=1: jump
  // straight into the purchase confirmation once the listing (and, when
  // logged in, the wallet) are ready. Guests get the modal too — their
  // checkout happens right there.
  useEffect(() => {
    if (autoBuyRef.current) return;
    if (searchParams.get('buy') !== '1') return;
    if (!listing || listing.status !== 'active' || authLoading) return;
    if (user && (!walletFetched || user.id === listing.seller_id)) return;
    autoBuyRef.current = true;
    openConfirmModal();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, authLoading, walletFetched, listing, searchParams]);

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
    setShowConfirm(true);
    trackBeginCheckout(listing, quantity);
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

  // Shared tail of both JazzCash flows (logged-in and guest): the payment
  // stopped being pending — turn it into a redirect, an error, or the
  // "still processing" note. Returns true when redirecting (the caller must
  // keep `buying` true so the button stays disabled until then).
  function settleJazzCashOutcome(payment) {
    if (payment?.status === 'completed' && payment.order_id) {
      const order = { id: payment.order_id, order_number: payment.order_number };
      trackPurchase(order, listing, quantity);
      setShowConfirm(false);
      setBuySuccess(`Order ${orderLabel(order)} placed! Redirecting...`);
      setTimeout(() => router.push(orderPath(order)), 1500);
      return true;
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
    return false;
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
      if (settleJazzCashOutcome(payment)) return;
    } catch (err) {
      setBuyError(err.message);
    }
    buyingRef.current = false;
    setBuying(false);
  }

  async function handleGuestBuy() {
    if (buyingRef.current) return;
    const mobile = jazzCashMobile.trim();
    const email = guestEmail.trim();
    if (!GUEST_EMAIL_REGEX.test(email)) {
      setBuyError('Enter a valid email address — your order and receipt go there.');
      return;
    }
    if (!JAZZCASH_MOBILE_REGEX.test(mobile)) {
      setBuyError('Enter a valid JazzCash mobile number (e.g., 03001234567).');
      return;
    }
    buyingRef.current = true;
    setBuyError('');
    setBuySuccess('');
    setBuying(true);
    try {
      const data = await initiateGuestJazzCashPurchase(listing.id, quantity, mobile, email, checkoutFieldValues);
      // The response set login cookies for the newly created account — adopt
      // the session so payment polling, the order page and any retry all run
      // logged in (a retry against the guest endpoint would be refused).
      fetchUser().catch(() => {});
      let payment = data.payment;
      if (payment.status === 'pending') {
        payment = await pollJazzCashPayment(payment.id);
      }
      if (settleJazzCashOutcome(payment)) return;
    } catch (err) {
      if (err.accountCreated) fetchUser().catch(() => {});
      setBuyError(err.code === 'account_exists'
        ? 'This email already has a GamesBazaar account — log in to finish your order.'
        : err.message);
    }
    buyingRef.current = false;
    setBuying(false);
  }

  function handleConfirmPurchase() {
    if (!user) {
      handleGuestBuy();
      return;
    }
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
  // Out of stock (status not active): the page stays up — same URL, title and
  // schema — but the buy box turns into "here's what you can get instead".
  const isOutOfStock = listing.status !== 'active';
  const alternatives = isOutOfStock ? listingAlternatives(listing) : [];
  const browsePath = isOutOfStock ? listingBrowsePath(listing) : null;
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

  // For guests who'd rather sign in: the login round-trip comes back to this
  // listing with the same amount and the confirmation step waiting.
  function loginToBuyHref() {
    const params = new URLSearchParams(searchParams?.toString() || '');
    params.set('buy', '1');
    if (isCurrency || quantity > 1) params.set('qty', String(quantity));
    return loginHref(`/listing/${listing.id}?${params.toString()}`);
  }

  function stepCurrencyQty(delta) {
    let next = quantity + delta;
    next = Math.max(minQty, next);
    if (stock !== null) next = Math.min(stock, next);
    setQuantity(next);
    setQtyInput(String(next));
  }

  const totalPrice = (listing.price * quantity).toFixed(2);
  // Flat checkout service fee from the backend (0 = no fee, no fee rows).
  // Logged-in buyers read it from the wallet payload; guests from the
  // public checkout config — both are the same backend value.
  const serviceFee = wallet
    ? (parseFloat(wallet.checkout_service_fee) || 0)
    : (parseFloat(checkoutConfig?.checkout_service_fee) || 0);
  const orderTotal = parseFloat(totalPrice) + serviceFee;
  const walletBalance = wallet ? parseFloat(wallet.balance) : 0;
  const hasBalance = wallet && walletBalance >= orderTotal;
  const jazzCashEnabled = wallet
    ? Boolean(wallet.jazzcash_enabled)
    : Boolean(checkoutConfig?.jazzcash_enabled);
  const canBuy = hasBalance || jazzCashEnabled;
  const isInstant = listing.is_auto_delivery || listing.instant_delivery;
  const sellerRating = listing.seller_avg_rating ?? null;
  // The reviews panel below already knows the true total; prefer it once loaded.
  const sellerReviewCount = reviewPagination?.count ?? listing.seller_review_count ?? 0;
  const requiredCheckoutFields = listing.required_checkout_fields || [];
  const checkoutFieldsFilled = requiredCheckoutFields.every(
    (f) => (checkoutFieldValues[f.key] || '').trim()
  );
  // JazzCash only covers what the wallet is missing, subject to the gateway's
  // minimum charge — anything above the shortfall lands back in the wallet.
  const payWithJazzCash = !hasBalance && jazzCashEnabled;
  const walletApplied = Math.min(walletBalance, orderTotal);
  const jazzCashShortfall = Math.max(0, orderTotal - walletBalance);
  const jazzCashCharge = Math.max(jazzCashShortfall, MIN_JAZZCASH_PAYMENT);
  const jazzCashChange = jazzCashCharge - jazzCashShortfall;
  // The initiate endpoint answers "pending" right away and we poll while the
  // buyer approves on their phone, so the prompt has to show for the whole
  // buying window — initiation and polling both.
  const jazzCashInFlight = payWithJazzCash && buying;
  // A failed JazzCash attempt usually means the buyer has no JazzCash wallet,
  // not that they mistyped — so the error has to name the other rails we
  // actually accept. Without this they just retry the same number.
  const paymentFallback = (
    <div className="alert alert-info" style={{ marginTop: '8px', marginBottom: 0 }}>
      <strong>No JazzCash account?</strong>
      <div style={{ marginTop: '4px', fontWeight: 400 }}>
        {user ? (
          <>
            You can also pay by Easypaisa or bank transfer.{' '}
            <Link href="/wallet" className="buy-topup-link">Add funds to your wallet</Link>{' '}
            and come back to finish this order.
          </>
        ) : (
          <>
            You can also pay by Easypaisa or bank transfer — tap{' '}
            <strong>Buy on WhatsApp</strong> and we&apos;ll sort it out in chat.
          </>
        )}
      </div>
    </div>
  );

  return (
    <div className="container">
      <div className="page-header">
        {/* Home › Game › Category, each a real link to its page (SEO fix #2);
            the layout emits the same trail as BreadcrumbList JSON-LD. */}
        <nav className="breadcrumb" aria-label="Breadcrumb">
          {listingBreadcrumbs(listing).map((crumb, index) => (
            <Fragment key={`${index}-${crumb.name}`}>
              {index > 0 && <span className="breadcrumb-sep">›</span>}
              {crumb.path
                ? <Link href={crumb.path}>{crumb.name}</Link>
                : <span>{crumb.name}</span>}
            </Fragment>
          ))}
        </nav>
      </div>

      <div className="listing-detail-layout">
        {/* The title spans both columns, so the buy box on the right and the
            seller card on the left always start on the same line no matter how
            many lines the title wraps to. */}
        <div className="listing-detail-header">
          {/* Same name as the page <title> and Product JSON-LD: brand and
              product word on gift cards / top-ups ("Steam 5 USD (Argentina)
              Gift Card"), the seller-template boilerplate stripped on
              accounts ("ELDEN RING (PC) Steam Account"), the bare title
              everywhere else. The stored title is never changed. */}
          <h1 className="listing-detail-title">{listingDisplayName(listing) || listing.title}</h1>

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
        </div>

        {/* Left column: who you're buying from, then the details */}
        <div className="listing-detail-main">
          {/* Who you are buying from + when it arrives — the two facts a buyer
              checks before price, so they sit above the fold on the left. */}
          <div className="listing-seller-card">
            <div className="listing-seller-row">
              <div className="listing-card-avatar-wrap">
                <div className="listing-seller-avatar">
                  <img
                    src={listing.seller_avatar_url || '/avatar-default.svg'}
                    alt={listing.seller_name}
                    style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }}
                  />
                </div>
              </div>
              <div className="listing-seller-info">
                <span className="seller-name-row">
                  <Link href={`/seller/${listing.seller_name}`} className="listing-seller-name">
                    {listing.seller_name}
                  </Link>
                  {listing.seller_is_official_store && <OfficialStoreBadge />}
                </span>
                <div className="listing-seller-meta">
                  {sellerRating !== null && sellerRating !== undefined ? (
                    <span className="listing-seller-rating">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" style={{ color: '#F59E0B' }}>
                        <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
                      </svg>
                      <strong>{sellerRating.toFixed(1)}</strong>
                      {sellerReviewCount > 0 && (
                        <span className="listing-seller-rating-count">
                          ({formatAmount(sellerReviewCount)} review{sellerReviewCount === 1 ? '' : 's'})
                        </span>
                      )}
                    </span>
                  ) : (
                    <span className="listing-seller-rating-count">No reviews yet</span>
                  )}
                  {/* No presence text at all — the avatar dot carries it. */}
                </div>
              </div>
            </div>

            <div className="listing-seller-delivery">
              {isInstant ? (
                <>
                  <svg className="instant-delivery-icon" width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z"/>
                  </svg>
                  <span><strong>Instant delivery</strong> — sent automatically right after payment</span>
                </>
              ) : (
                <>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12 6 12 12 16 14"/>
                  </svg>
                  <span>
                    {listing.delivery_time
                      ? <>Delivery time — <strong>{listing.delivery_time}</strong></>
                      : 'Delivered on your order page after purchase'}
                  </span>
                </>
              )}
            </div>
          </div>

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

        {/* Right column: the buy box. */}
        <div className="listing-detail-side">
          <div className="listing-detail-price-card">
              <div className="listing-detail-price">
                PKR {isCurrency ? formatUnitPrice(listing.price) : listing.price}
                {isCurrency && unitName && <span className="currency-unit-suffix"> / {unitName}</span>}
              </div>

              {/* Sold count — social proof; hidden until the first sale */}
              {Number(listing.sales_count) > 0 && (
                <div className="listing-stock listing-sales-count">
                  {Number(listing.sales_count).toLocaleString()} sold
                </div>
              )}

              {/* Stock */}
              {!isOutOfStock && listing.quantity !== null && listing.quantity > 0 && (
                <div className="listing-stock">
                  {isCurrency ? `${formatAmount(listing.quantity)} ${unitName}`.trim() : listing.quantity} in stock
                </div>
              )}
              {isCurrency && !isOutOfStock && (
                <div className="listing-stock">
                  Min. purchase: {formatAmount(minQty)} {unitName}
                </div>
              )}
              {isOutOfStock && (
                <div className="listing-unavailable">
                  <div className="listing-sold-badge">Out of stock</div>
                  <p className="listing-unavailable-text">
                    This one isn&apos;t available right now.
                    {browsePath && (
                      <>
                        {' '}Browse the rest of{' '}
                        <Link href={browsePath} className="buy-topup-link">
                          {[listing.game_name, listing.category_name].filter(Boolean).join(' ')}
                        </Link>.
                      </>
                    )}
                  </p>
                  {alternatives.length > 0 && (
                    <div className="listing-alternatives">
                      <div className="listing-alternatives-title">Available now</div>
                      <ul className="listing-alternatives-list">
                        {alternatives.map((alt) => (
                          <li key={alt.id}>
                            <Link href={`/listing/${alt.id}`} className="listing-alternative">
                              <span className="listing-alternative-name">{alt.option_name || alt.title}</span>
                              <span className="listing-alternative-price">PKR {formatAmount(alt.price)}</span>
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* Buy section */}
              {!isOwnListing && listing.status === 'active' && (
                <div className="buy-section">
                  {/* Logged out visitors get the same box and the same modal —
                      guest checkout asks for their email in there instead of
                      sending anyone to a signup page first. */}

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
                      Total: <strong>PKR {formatPKR(orderTotal)}</strong>
                      {serviceFee > 0 && <> (incl. PKR {formatPKR(serviceFee)} service fee)</>}
                    </div>
                  )}

                  {/* Wallet balance (logged-in only — guests have no wallet) */}
                  {wallet && (
                    <div className="buy-wallet-info">
                      Wallet: <strong>PKR {Number(wallet.balance).toLocaleString('en-PK', { minimumFractionDigits: 2 })}</strong>
                      {!hasBalance && (
                        <Link href="/wallet" className="buy-topup-link">Add Funds →</Link>
                      )}
                    </div>
                  )}

                  {buyError && <div className="alert alert-error" style={{ marginTop: '8px', marginBottom: 0 }}>{buyError}</div>}
                  {buyError && payWithJazzCash && paymentFallback}
                  {buySuccess && <div className="alert alert-success" style={{ marginTop: '8px' }}>{buySuccess}</div>}

                  <button
                    className="btn btn-primary btn-full buy-now-btn"
                    onClick={openConfirmModal}
                    disabled={
                      buying || !currencyQtyValid ||
                      (user ? !canBuy : Boolean(checkoutConfig) && !jazzCashEnabled)
                    }
                  >
                    {buying ? 'Purchasing...' : `Buy Now — PKR ${formatPKR(orderTotal)}`}
                  </button>
                  {payWithJazzCash && (
                    <div className="form-hint" style={{ marginTop: '6px', textAlign: 'center' }}>
                      {walletApplied > 0
                        ? `Pay PKR ${formatPKR(walletApplied)} from your wallet + PKR ${formatPKR(jazzCashCharge)} via JazzCash`
                        : 'Pay directly with JazzCash — no wallet balance needed'}
                    </div>
                  )}

                  {/* Second buy rail: close the sale in a WhatsApp chat
                      instead. The helper records the click (with the Meta
                      pixel cookies) before opening the chat — see
                      lib/whatsapp.js. */}
                  <button
                    type="button"
                    className="btn btn-whatsapp btn-full"
                    onClick={() => openWhatsAppChat({ listing, quantity })}
                    disabled={buying}
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                      <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z" />
                    </svg>
                    Buy on WhatsApp
                  </button>
                </div>
              )}

              {/* What the buyer is protected by — inside the buy box, right
                  under the button, where "is this safe?" gets asked. */}
              <div className="trust-signals">
                <div className="trust-signal">
                  <svg className="trust-signal-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                    <polyline points="9 12 11 14 15 10"/>
                  </svg>
                  <div className="trust-signal-body">
                    <div className="trust-signal-title">Secure Payment</div>
                    <div className="trust-signal-text">
                      Anything wrong with your order? Message us — we make it
                      right or refund straight to your wallet.
                    </div>
                  </div>
                </div>

                {isInstant && (
                  <div className="trust-signal">
                    <svg className="trust-signal-icon" width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z"/>
                    </svg>
                    <div className="trust-signal-body">
                      <div className="trust-signal-title">Instant Delivery</div>
                      <div className="trust-signal-text">
                        Delivered automatically the moment your payment goes through.
                      </div>
                    </div>
                  </div>
                )}

              </div>
            </div>

        </div>

        {/* Left column, under the description: seller reviews */}
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
                    <ReviewPhotos images={review.images} />
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
      </div>

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
                {serviceFee > 0 && (
                  <>
                    <div className="confirm-order-row">
                      <span className="confirm-order-label">Items</span>
                      <span className="confirm-order-value">PKR {formatPKR(totalPrice)}</span>
                    </div>
                    <div className="confirm-order-row">
                      <span className="confirm-order-label">Service Fee</span>
                      <span className="confirm-order-value">PKR {formatPKR(serviceFee)}</span>
                    </div>
                  </>
                )}
                <div className="confirm-order-row confirm-order-row-total">
                  <span className="confirm-order-label">Total</span>
                  <span className="confirm-order-value confirm-order-total">PKR {formatPKR(orderTotal)}</span>
                </div>
              </div>

              {/* Auto-fulfilled top-ups / Steam gifts: buyer info the supplier
                  needs (player ID, server, friend invite link). */}
              {requiredCheckoutFields.map((field, idx) => {
                const isSelect = field.type === 'select' && Array.isArray(field.options) && field.options.length > 0;
                return (
                  <div className="form-group" key={field.key} style={{ marginBottom: 0 }}>
                    <label className="form-label">{field.label} *</label>
                    {isSelect ? (
                      <Select
                        value={checkoutFieldValues[field.key] || ''}
                        onChange={(value) => {
                          setCheckoutFieldValues((prev) => ({ ...prev, [field.key]: value }));
                        }}
                        options={field.options.map((o) => ({ value: o.value, label: o.label }))}
                        placeholder={`Select ${field.label}...`}
                        ariaLabel={field.label}
                        disabled={buying}
                      />
                    ) : (
                      <input
                        type="text"
                        className="form-input"
                        value={checkoutFieldValues[field.key] || ''}
                        onChange={(e) => {
                          setCheckoutFieldValues((prev) => ({ ...prev, [field.key]: e.target.value }));
                        }}
                        placeholder={field.placeholder || field.label}
                        maxLength={100}
                        disabled={buying}
                      />
                    )}
                    {(field.hint || idx === requiredCheckoutFields.length - 1) && (
                      <span className="form-hint">
                        {field.hint || 'The top-up goes directly to this account — a wrong ID cannot be reversed.'}
                      </span>
                    )}
                  </div>
                );
              })}

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
                        PKR {formatPKR(walletBalance - orderTotal)}
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

              {/* Guest checkout: where the order (and the account we quietly
                  create for it) goes. */}
              {!user && (
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label">Email *</label>
                  <input
                    type="email"
                    className="form-input"
                    value={guestEmail}
                    onChange={(e) => setGuestEmail(e.target.value)}
                    placeholder="you@example.com"
                    maxLength={254}
                    disabled={buying}
                  />
                  <span className="form-hint">
                    Your order and receipt go to this email — an account is
                    created for you automatically, no password needed now.
                  </span>
                  <div className="form-hint" style={{ marginTop: '8px' }}>
                    Already have an account?{' '}
                    <Link href={loginToBuyHref()} className="buy-topup-link">Log in</Link>
                  </div>
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
                    {user ? (
                      <>
                        No JazzCash? Pay by Easypaisa or bank transfer instead —{' '}
                        <Link href="/wallet" className="buy-topup-link">add funds to your wallet</Link> and
                        come back to complete the purchase.
                      </>
                    ) : (
                      <>
                        No JazzCash? Pay by Easypaisa or bank transfer instead — use
                        the <strong>Buy on WhatsApp</strong> button on this listing.
                      </>
                    )}
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
                Anything wrong with your order? Message us from the order page — we make it right or refund your wallet.
              </div>

              {!user && (
                <div className="form-hint" style={{ marginTop: 0 }}>
                  By placing this order you agree to the{' '}
                  <Link href="/terms-of-service" className="buy-topup-link" target="_blank">Terms of Service</Link>.
                </div>
              )}

              {buyError && <div className="alert alert-error" style={{ margin: '0' }}>{buyError}</div>}
              {buyError && payWithJazzCash && paymentFallback}
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
                  `Confirm Purchase — PKR ${formatPKR(orderTotal)}`
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

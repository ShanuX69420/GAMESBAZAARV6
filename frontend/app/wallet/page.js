'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import {
  getWallet, getTopUpRequests, requestWithdraw, getWithdrawRequests,
  initiateJazzCashTopUp, pollJazzCashPayment,
} from '@/lib/api';

const TRANSACTION_PAGE_SIZE = 20;
const TOPUP_PAGE_SIZE = 20;
const WITHDRAW_PAGE_SIZE = 20;
const MIN_TOP_UP_AMOUNT = 500;
const MIN_TOP_UP_MESSAGE = 'Minimum top-up is PKR 500.';
const MAX_TOP_UP_AMOUNT = 10000;
const MAX_TOP_UP_MESSAGE = 'Max is 10000. Please contact support if you want to add more.';
const MIN_WITHDRAW_AMOUNT = 500;
const JAZZCASH_MOBILE_REGEX = /^03\d{9}$/;
const JAZZCASH_MOBILE_MESSAGE = 'Enter a valid JazzCash mobile number (e.g., 03001234567).';
const WHATSAPP_NUMBER = '923712101998';
const WHATSAPP_NUMBER_DISPLAY = '0371 2101998';

export default function WalletPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [walletData, setWalletData] = useState(null);
  const [transactionPagination, setTransactionPagination] = useState(null);
  const [topUpRequests, setTopUpRequests] = useState([]);
  const [topUpPagination, setTopUpPagination] = useState(null);
  const [withdrawRequests, setWithdrawRequests] = useState([]);
  const [withdrawPagination, setWithdrawPagination] = useState(null);
  const [showTopUp, setShowTopUp] = useState(false);
  const [showWithdraw, setShowWithdraw] = useState(false);
  const [topUpAmount, setTopUpAmount] = useState('');
  const [topUpMethod, setTopUpMethod] = useState('jazzcash');
  const [jazzCashMobile, setJazzCashMobile] = useState('');
  const [jazzCashWaiting, setJazzCashWaiting] = useState(false);
  const [withdrawAmount, setWithdrawAmount] = useState('');
  const [withdrawMethod, setWithdrawMethod] = useState('JazzCash');
  const [withdrawAccountTitle, setWithdrawAccountTitle] = useState('');
  const [withdrawAccount, setWithdrawAccount] = useState('');
  const [withdrawBankName, setWithdrawBankName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [loadingMoreTransactions, setLoadingMoreTransactions] = useState(false);
  const [loadingMoreTopUps, setLoadingMoreTopUps] = useState(false);
  const [loadingMoreWithdraws, setLoadingMoreWithdraws] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    if (!loading && !user) router.push('/login');
  }, [user, loading, router]);

  useEffect(() => {
    if (user) {
      loadData();
    }
  }, [user]);

  async function loadData() {
    try {
      const [wallet, topups, withdraws] = await Promise.all([
        getWallet({ limit: TRANSACTION_PAGE_SIZE, offset: 0 }),
        getTopUpRequests({ limit: TOPUP_PAGE_SIZE, offset: 0 }),
        getWithdrawRequests({ limit: WITHDRAW_PAGE_SIZE, offset: 0 }),
      ]);
      setWalletData(wallet);
      setTransactionPagination(wallet.transaction_pagination || null);
      setTopUpRequests(topups.topup_requests || []);
      setTopUpPagination(topups.pagination || null);
      setWithdrawRequests(withdraws.withdraw_requests || []);
      setWithdrawPagination(withdraws.pagination || null);
    } catch (err) {
      console.error(err);
    }
  }

  async function loadMoreTransactions() {
    if (!transactionPagination?.next_offset || loadingMoreTransactions) return;
    setLoadingMoreTransactions(true);
    try {
      const wallet = await getWallet({
        limit: TRANSACTION_PAGE_SIZE,
        offset: transactionPagination.next_offset,
      });
      setWalletData(prev => ({
        ...wallet,
        transactions: [
          ...(prev?.transactions || []),
          ...(wallet.transactions || []),
        ],
      }));
      setTransactionPagination(wallet.transaction_pagination || null);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingMoreTransactions(false);
    }
  }

  async function loadMoreTopUps() {
    if (!topUpPagination?.next_offset || loadingMoreTopUps) return;
    setLoadingMoreTopUps(true);
    try {
      const topups = await getTopUpRequests({
        limit: TOPUP_PAGE_SIZE,
        offset: topUpPagination.next_offset,
      });
      setTopUpRequests(prev => [
        ...prev,
        ...(topups.topup_requests || []),
      ]);
      setTopUpPagination(topups.pagination || null);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingMoreTopUps(false);
    }
  }

  async function loadMoreWithdraws() {
    if (!withdrawPagination?.next_offset || loadingMoreWithdraws) return;
    setLoadingMoreWithdraws(true);
    try {
      const withdraws = await getWithdrawRequests({
        limit: WITHDRAW_PAGE_SIZE,
        offset: withdrawPagination.next_offset,
      });
      setWithdrawRequests(prev => [
        ...prev,
        ...(withdraws.withdraw_requests || []),
      ]);
      setWithdrawPagination(withdraws.pagination || null);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingMoreWithdraws(false);
    }
  }

  function handleTopUpAmountChange(e) {
    const value = e.target.value;
    setTopUpAmount(value);
    if (Number(value) > MAX_TOP_UP_AMOUNT) {
      setSuccess('');
      setError(MAX_TOP_UP_MESSAGE);
    } else if (error === MAX_TOP_UP_MESSAGE) {
      setError('');
    }
  }

  async function handleJazzCashTopUp(e) {
    e.preventDefault();
    setError('');
    setSuccess('');
    if (Number(topUpAmount) < MIN_TOP_UP_AMOUNT) {
      setError(MIN_TOP_UP_MESSAGE);
      return;
    }
    if (Number(topUpAmount) > MAX_TOP_UP_AMOUNT) {
      setError(MAX_TOP_UP_MESSAGE);
      return;
    }
    const mobile = jazzCashMobile.trim();
    if (!JAZZCASH_MOBILE_REGEX.test(mobile)) {
      setError(JAZZCASH_MOBILE_MESSAGE);
      return;
    }
    setSubmitting(true);
    try {
      let payment = await initiateJazzCashTopUp(topUpAmount, mobile);
      if (payment.status === 'pending') {
        setJazzCashWaiting(true);
        payment = await pollJazzCashPayment(payment.id);
      }
      if (payment?.status === 'completed') {
        setSuccess(`PKR ${Number(payment.amount).toLocaleString('en-PK', { minimumFractionDigits: 2 })} added to your wallet via JazzCash!`);
        setTopUpAmount('');
        setJazzCashMobile('');
        setShowTopUp(false);
        await loadData();
      } else if (payment?.status === 'failed') {
        setError(payment.response_message || 'JazzCash payment failed. Please try again.');
      } else {
        setSuccess('Your JazzCash payment is still processing. Your wallet will be credited automatically once JazzCash confirms it.');
        setShowTopUp(false);
        await loadData();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setJazzCashWaiting(false);
      setSubmitting(false);
    }
  }

  async function handleWithdraw(e) {
    e.preventDefault();
    setError('');
    setSuccess('');
    const amount = Number(withdrawAmount);
    if (amount < MIN_WITHDRAW_AMOUNT) {
      setError(`Minimum withdrawal amount is PKR ${MIN_WITHDRAW_AMOUNT}.`);
      return;
    }
    if (!withdrawAccountTitle.trim()) {
      setError('Account title is required.');
      return;
    }
    if (!withdrawAccount.trim()) {
      setError('Account details are required.');
      return;
    }
    if (withdrawMethod === 'Bank Transfer' && !withdrawBankName.trim()) {
      setError('Bank name is required for bank transfers.');
      return;
    }
    setSubmitting(true);
    try {
      await requestWithdraw(
        withdrawAmount,
        withdrawMethod,
        withdrawAccountTitle.trim(),
        withdrawAccount.trim(),
        withdrawMethod === 'Bank Transfer' ? withdrawBankName.trim() : '',
      );
      setSuccess('Withdrawal request submitted! Admin will process it shortly.');
      setWithdrawAmount('');
      setWithdrawMethod('JazzCash');
      setWithdrawAccountTitle('');
      setWithdrawAccount('');
      setWithdrawBankName('');
      setShowWithdraw(false);
      await loadData();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  const amountOverLimit = Number(topUpAmount) > MAX_TOP_UP_AMOUNT;
  const topUpBelowMin = topUpAmount !== '' && Number(topUpAmount) < MIN_TOP_UP_AMOUNT;
  const jazzCashEnabled = Boolean(walletData?.jazzcash_enabled);
  const activeTopUpMethod = jazzCashEnabled ? topUpMethod : 'manual';
  const withdrawBelowMin = withdrawAmount !== '' && Number(withdrawAmount) < MIN_WITHDRAW_AMOUNT;
  const currentBalance = walletData ? Number(walletData.balance) : 0;
  const heldBalance = walletData ? Number(walletData.held_balance || 0) : 0;
  const withdrawExceedsBalance = withdrawAmount !== '' && Number(withdrawAmount) > currentBalance;
  const whatsappMessage = `Hi! I want to top up my GamesBazaar wallet.\nUsername: ${user?.username || ''}${topUpAmount ? `\nAmount: Rs ${topUpAmount}` : ''}`;
  const whatsappUrl = `https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(whatsappMessage)}`;

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
        <h1 className="page-title">💰 Wallet</h1>
        <p className="page-subtitle">Manage your funds and transactions</p>
      </div>

      {/* Balance Card */}
      <div className="wallet-balance-card">
        <div className="wallet-balance-label">Available Balance</div>
        <div className="wallet-balance-amount">
          PKR {walletData ? Number(walletData.balance).toLocaleString('en-PK', { minimumFractionDigits: 2 }) : '0.00'}
        </div>
        {heldBalance > 0 && (
          <div className="wallet-balance-label" style={{ marginTop: '8px' }}>
            <Link href="/wallet/held-balance" className="held-balance-link">
              Pending balance: PKR {heldBalance.toLocaleString('en-PK', { minimumFractionDigits: 2 })}
              <span className="held-arrow">→</span>
            </Link>
          </div>
        )}
        <div className="wallet-actions">
          <button
            className="btn btn-primary"
            onClick={() => { setShowTopUp(!showTopUp); setShowWithdraw(false); setError(''); setSuccess(''); }}
          >
            {showTopUp ? 'Cancel' : '+ Add Funds'}
          </button>
          <button
            className="btn btn-withdraw"
            onClick={() => { setShowWithdraw(!showWithdraw); setShowTopUp(false); setError(''); setSuccess(''); }}
          >
            {showWithdraw ? 'Cancel' : '↗ Withdraw'}
          </button>
        </div>
      </div>

      {/* Success/Error */}
      {success && <div className="alert alert-success">{success}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {/* Top-Up Form */}
      {showTopUp && (
        <div className="wallet-topup-card">
          <h2 className="card-title">Add Funds</h2>

          {/* Method selector */}
          {jazzCashEnabled && (
            <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
              <button
                type="button"
                className={activeTopUpMethod === 'jazzcash' ? 'btn btn-primary' : 'btn btn-outline'}
                onClick={() => { setTopUpMethod('jazzcash'); setError(''); setSuccess(''); }}
                disabled={submitting}
              >
                ⚡ JazzCash — Instant
              </button>
              <button
                type="button"
                className={activeTopUpMethod === 'manual' ? 'btn btn-primary' : 'btn btn-outline'}
                onClick={() => { setTopUpMethod('manual'); setError(''); setSuccess(''); }}
                disabled={submitting}
              >
                💬 WhatsApp
              </button>
            </div>
          )}

          {/* JazzCash instant top-up */}
          {activeTopUpMethod === 'jazzcash' && (
            <>
              <p className="card-text">
                Enter your JazzCash mobile number and approve the payment request
                in your JazzCash app. Your wallet is credited instantly.
              </p>
              <form onSubmit={handleJazzCashTopUp} className="topup-form">
                <div className="form-group">
                  <label className="form-label">Amount (PKR) *</label>
                  <input
                    type="number"
                    className="form-input"
                    value={topUpAmount}
                    onChange={handleTopUpAmountChange}
                    placeholder={`Min. ${MIN_TOP_UP_AMOUNT}`}
                    min={MIN_TOP_UP_AMOUNT}
                    step="0.01"
                    required
                  />
                  {topUpBelowMin && (
                    <span className="form-hint form-error-text">{MIN_TOP_UP_MESSAGE}</span>
                  )}
                  {amountOverLimit && (
                    <span className="form-hint form-error-text">{MAX_TOP_UP_MESSAGE}</span>
                  )}
                </div>
                <div className="form-group">
                  <label className="form-label">JazzCash Mobile Number *</label>
                  <input
                    type="tel"
                    className="form-input"
                    value={jazzCashMobile}
                    onChange={(e) => setJazzCashMobile(e.target.value)}
                    placeholder="03001234567"
                    maxLength={11}
                    required
                  />
                  <span className="form-hint">The JazzCash account that will be charged.</span>
                </div>
                {jazzCashWaiting && (
                  <div className="alert alert-success" style={{ marginBottom: '12px' }}>
                    ⏳ Payment request sent! Approve it in your JazzCash app — this
                    page will update automatically.
                  </div>
                )}
                <button type="submit" className="btn btn-primary" disabled={submitting || amountOverLimit || topUpBelowMin}>
                  {submitting
                    ? (jazzCashWaiting ? 'Waiting for confirmation...' : 'Sending request...')
                    : 'Pay with JazzCash'}
                </button>
              </form>
            </>
          )}

          {activeTopUpMethod === 'manual' && (
          <>
          <p className="card-text">
            Message us on WhatsApp with the amount you want to add. We&apos;ll
            confirm the payment with you and credit your wallet within minutes.
          </p>

          {/* WhatsApp Details Card */}
          <div className="topup-payment-details">
            <div className="topup-payment-details-header">
              <span className="topup-payment-details-icon">💬</span>
              <strong>Top Up via WhatsApp</strong>
            </div>
            <div className="topup-payment-details-body">
              <div className="topup-detail-row">
                <span className="topup-detail-label">WhatsApp</span>
                <span className="topup-detail-value">{WHATSAPP_NUMBER_DISPLAY}</span>
              </div>
              <div className="topup-detail-row">
                <span className="topup-detail-label">Name</span>
                <span className="topup-detail-value">Games Bazaar</span>
              </div>
            </div>
            <div className="topup-payment-details-footer">
              <span>⚡</span>
              <span>Tap the button below — your username is included in the message automatically, so we know exactly which account to credit.</span>
            </div>
          </div>

          <div className="topup-form">
            <div className="form-group">
              <label className="form-label">Amount (PKR)</label>
              <input
                type="number"
                className="form-input"
                value={topUpAmount}
                onChange={(e) => setTopUpAmount(e.target.value)}
                placeholder={`Min. ${MIN_TOP_UP_AMOUNT}`}
                min={MIN_TOP_UP_AMOUNT}
                step="0.01"
              />
              {topUpBelowMin && (
                <span className="form-hint form-error-text">{MIN_TOP_UP_MESSAGE}</span>
              )}
            </div>
            <a
              className="btn btn-whatsapp"
              href={whatsappUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              💬 Message us on WhatsApp
            </a>
          </div>
          </>
          )}
        </div>
      )}

      {/* Withdraw Form */}
      {showWithdraw && (
        <div className="wallet-withdraw-card">
          <h2 className="card-title">Request Withdrawal</h2>
          <p className="card-text">
            Enter the amount and your payment details. Your balance will be held until
            admin processes the withdrawal. Minimum withdrawal is <strong>PKR {MIN_WITHDRAW_AMOUNT}</strong>.
          </p>
          <form onSubmit={handleWithdraw} className="topup-form">
            <div className="form-group">
              <label className="form-label">Amount (PKR) *</label>
              <input
                type="number"
                className="form-input"
                value={withdrawAmount}
                onChange={(e) => setWithdrawAmount(e.target.value)}
                placeholder={`Min. ${MIN_WITHDRAW_AMOUNT}`}
                min={MIN_WITHDRAW_AMOUNT}
                step="0.01"
                required
              />
              {withdrawBelowMin && (
                <span className="form-hint form-error-text">Minimum withdrawal is PKR {MIN_WITHDRAW_AMOUNT}.</span>
              )}
              {withdrawExceedsBalance && !withdrawBelowMin && (
                <span className="form-hint form-error-text">Amount exceeds your available balance.</span>
              )}
            </div>
            <div className="form-group">
              <label className="form-label">Payment Method *</label>
              <select
                className="form-input"
                value={withdrawMethod}
                onChange={(e) => setWithdrawMethod(e.target.value)}
                required
              >
                <option value="JazzCash">JazzCash</option>
                <option value="EasyPaisa">EasyPaisa</option>
                <option value="Bank Transfer">Bank Transfer</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Account Title *</label>
              <input
                type="text"
                className="form-input"
                value={withdrawAccountTitle}
                onChange={(e) => setWithdrawAccountTitle(e.target.value)}
                placeholder="Name on the account"
                required
              />
            </div>
            {withdrawMethod === 'Bank Transfer' && (
              <div className="form-group">
                <label className="form-label">Bank Name *</label>
                <input
                  type="text"
                  className="form-input"
                  value={withdrawBankName}
                  onChange={(e) => setWithdrawBankName(e.target.value)}
                  placeholder="e.g., HBL, Meezan Bank, UBL"
                  required
                />
              </div>
            )}
            <div className="form-group">
              <label className="form-label">{withdrawMethod === 'Bank Transfer' ? 'IBAN / Account Number *' : 'Account Number *'}</label>
              <input
                type="text"
                className="form-input"
                value={withdrawAccount}
                onChange={(e) => setWithdrawAccount(e.target.value)}
                placeholder={withdrawMethod === 'Bank Transfer' ? 'e.g., PK36MEZN0001234567890123' : 'e.g., 03001234567'}
                required
              />
              <span className="form-hint">{withdrawMethod === 'Bank Transfer' ? 'Enter your IBAN or bank account number.' : 'Enter your mobile wallet number.'}</span>
            </div>
            <button type="submit" className="btn btn-withdraw" disabled={submitting || withdrawBelowMin || withdrawExceedsBalance}>
              {submitting ? 'Submitting...' : 'Submit Withdrawal Request'}
            </button>
          </form>
        </div>
      )}

      {/* Top-Up Requests */}
      {topUpRequests.length > 0 && (
        <section className="section">
          <h2 className="section-title">Top-Up Requests</h2>
          <div className="wallet-requests-list">
            {topUpRequests.map((req) => (
              <div key={req.id} className={`wallet-request-card wallet-request-${req.status}`}>
                <div className="wallet-request-header">
                  <div className="wallet-request-info">
                    <span className="wallet-request-amount">PKR {Number(req.amount).toLocaleString('en-PK', { minimumFractionDigits: 2 })}</span>
                    <span className="wallet-request-method">{req.payment_method || '—'}</span>
                  </div>
                  <div className="wallet-request-meta">
                    <span className={`status-pill status-${req.status === 'approved' ? 'active' : req.status === 'rejected' ? 'sold' : 'inactive'}`}>
                      {req.status === 'approved' ? '✅ Approved' : req.status === 'rejected' ? '❌ Rejected' : '⏳ Pending'}
                    </span>
                    <span className="wallet-request-date">{new Date(req.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
                {req.status !== 'pending' && req.admin_note && (
                  <div className={`wallet-request-note ${req.status === 'rejected' ? 'wallet-request-note-rejected' : 'wallet-request-note-approved'}`}>
                    <div className="wallet-request-note-label">
                      {req.status === 'rejected' ? '❌ Rejection Reason' : '📝 Admin Note'}
                    </div>
                    <div className="wallet-request-note-text">{req.admin_note}</div>
                  </div>
                )}
                {req.reviewed_at && (
                  <div className="wallet-request-reviewed">
                    Reviewed on {new Date(req.reviewed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </div>
                )}
              </div>
            ))}
            {topUpPagination?.next_offset !== null && topUpPagination?.next_offset !== undefined && (
              <button
                className="btn btn-outline btn-full"
                style={{ marginTop: '16px' }}
                onClick={loadMoreTopUps}
                disabled={loadingMoreTopUps}
              >
                {loadingMoreTopUps ? 'Loading...' : 'Load More Top-Ups'}
              </button>
            )}
          </div>
        </section>
      )}

      {/* Withdrawal Requests */}
      {withdrawRequests.length > 0 && (
        <section className="section">
          <h2 className="section-title">Withdrawal Requests</h2>
          <div className="wallet-requests-list">
            {withdrawRequests.map((req) => (
              <div key={req.id} className={`wallet-request-card wallet-request-${req.status}`}>
                <div className="wallet-request-header">
                  <div className="wallet-request-info">
                    <span className="wallet-request-amount">PKR {Number(req.amount).toLocaleString('en-PK', { minimumFractionDigits: 2 })}</span>
                    <span className="wallet-request-method">{req.payment_method || '—'} • {req.account_details || '—'}</span>
                  </div>
                  <div className="wallet-request-meta">
                    <span className={`status-pill status-${req.status === 'approved' ? 'active' : req.status === 'rejected' ? 'sold' : 'inactive'}`}>
                      {req.status === 'approved' ? '✅ Approved' : req.status === 'rejected' ? '❌ Rejected' : '⏳ Pending'}
                    </span>
                    <span className="wallet-request-date">{new Date(req.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
                {req.status !== 'pending' && req.admin_note && (
                  <div className={`wallet-request-note ${req.status === 'rejected' ? 'wallet-request-note-rejected' : 'wallet-request-note-approved'}`}>
                    <div className="wallet-request-note-label">
                      {req.status === 'rejected' ? '❌ Rejection Reason' : '📝 Admin Note'}
                    </div>
                    <div className="wallet-request-note-text">{req.admin_note}</div>
                  </div>
                )}
                {req.status === 'approved' && req.payment_receipt_url && (
                  <div className="wallet-request-receipt">
                    <div className="wallet-request-note-label">🧾 Payment Receipt</div>
                    <a href={req.payment_receipt_url} target="_blank" rel="noopener noreferrer" className="wallet-receipt-link">
                      <span>Open Receipt</span>
                    </a>
                  </div>
                )}
                {req.reviewed_at && (
                  <div className="wallet-request-reviewed">
                    Reviewed on {new Date(req.reviewed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </div>
                )}
              </div>
            ))}
            {withdrawPagination?.next_offset !== null && withdrawPagination?.next_offset !== undefined && (
              <button
                className="btn btn-outline btn-full"
                style={{ marginTop: '16px' }}
                onClick={loadMoreWithdraws}
                disabled={loadingMoreWithdraws}
              >
                {loadingMoreWithdraws ? 'Loading...' : 'Load More Withdrawals'}
              </button>
            )}
          </div>
        </section>
      )}

      {/* Transaction History */}
      <section className="section">
        <h2 className="section-title">Transaction History</h2>
        {walletData && walletData.transactions && walletData.transactions.length > 0 ? (
          <div className="listings-table-wrap">
            <table className="listings-table">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Amount</th>
                  <th>Balance After</th>
                  <th>Description</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {walletData.transactions.map((txn) => {
                  const isDebit = Boolean(txn.is_debit);
                  const displayAmount = txn.display_amount ?? txn.amount;
                  return (
                    <tr key={txn.id}>
                      <td>
                        <span className={`txn-type txn-${txn.transaction_type}`}>
                          {txn.transaction_type_display}
                        </span>
                      </td>
                      <td className={`txn-amount ${isDebit ? 'txn-debit' : 'txn-credit'}`}>
                        {isDebit ? '-' : '+'}PKR {displayAmount}
                      </td>
                      <td>PKR {txn.balance_after}</td>
                      <td className="txn-desc">{txn.description}</td>
                      <td>{new Date(txn.created_at).toLocaleDateString()}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {transactionPagination?.next_offset !== null && transactionPagination?.next_offset !== undefined && (
              <button
                className="btn btn-outline btn-full"
                style={{ marginTop: '16px' }}
                onClick={loadMoreTransactions}
                disabled={loadingMoreTransactions}
              >
                {loadingMoreTransactions ? 'Loading...' : 'Load More Transactions'}
              </button>
            )}
          </div>
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon">📊</div>
            <p>No transactions yet.</p>
          </div>
        )}
      </section>
    </div>
  );
}

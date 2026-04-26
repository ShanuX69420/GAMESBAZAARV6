'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { getWallet, requestTopUp, getTopUpRequests } from '@/lib/api';

const TRANSACTION_PAGE_SIZE = 20;
const TOPUP_PAGE_SIZE = 20;
const MAX_TOP_UP_AMOUNT = 10000;
const MAX_TOP_UP_MESSAGE = 'Max is 10000. Please contact support if you want to add more.';

export default function WalletPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [walletData, setWalletData] = useState(null);
  const [transactionPagination, setTransactionPagination] = useState(null);
  const [topUpRequests, setTopUpRequests] = useState([]);
  const [topUpPagination, setTopUpPagination] = useState(null);
  const [showTopUp, setShowTopUp] = useState(false);
  const [topUpAmount, setTopUpAmount] = useState('');
  const [paymentMethod, setPaymentMethod] = useState('JazzCash');
  const [txnId, setTxnId] = useState('');
  const [proofFile, setProofFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [loadingMoreTransactions, setLoadingMoreTransactions] = useState(false);
  const [loadingMoreTopUps, setLoadingMoreTopUps] = useState(false);
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
      const [wallet, topups] = await Promise.all([
        getWallet({ limit: TRANSACTION_PAGE_SIZE, offset: 0 }),
        getTopUpRequests({ limit: TOPUP_PAGE_SIZE, offset: 0 }),
      ]);
      setWalletData(wallet);
      setTransactionPagination(wallet.transaction_pagination || null);
      setTopUpRequests(topups.topup_requests || []);
      setTopUpPagination(topups.pagination || null);
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

  async function handleTopUp(e) {
    e.preventDefault();
    setError('');
    setSuccess('');
    if (Number(topUpAmount) > MAX_TOP_UP_AMOUNT) {
      setError(MAX_TOP_UP_MESSAGE);
      return;
    }
    if (!txnId.trim()) {
      setError('Transaction ID / reference is required.');
      return;
    }
    if (!proofFile) {
      setError('Payment proof screenshot is required.');
      return;
    }
    setSubmitting(true);
    try {
      await requestTopUp(topUpAmount, paymentMethod, txnId.trim(), proofFile);
      setSuccess('Top-up request submitted! Admin will review it shortly.');
      setTopUpAmount('');
      setPaymentMethod('JazzCash');
      setTxnId('');
      setProofFile(null);
      setShowTopUp(false);
      await loadData();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  const amountOverLimit = Number(topUpAmount) > MAX_TOP_UP_AMOUNT;

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
        <div className="wallet-actions">
          <button className="btn btn-primary" onClick={() => setShowTopUp(!showTopUp)}>
            {showTopUp ? 'Cancel' : '+ Add Funds'}
          </button>
        </div>
      </div>

      {/* Success/Error */}
      {success && <div className="alert alert-success">{success}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {/* Top-Up Form */}
      {showTopUp && (
        <div className="wallet-topup-card">
          <h2 className="card-title">Request Top-Up</h2>
          <p className="card-text">
            Send payment via JazzCash, EasyPaisa, or Bank Transfer, then submit your details below.
            Admin will verify and credit your wallet.
          </p>
          <form onSubmit={handleTopUp} className="topup-form">
            <div className="form-group">
              <label className="form-label">Amount (PKR) *</label>
              <input
                type="number"
                className="form-input"
                value={topUpAmount}
                onChange={handleTopUpAmountChange}
                placeholder="e.g. 1000"
                min="1"
                step="0.01"
                required
              />
              {amountOverLimit && (
                <span className="form-hint form-error-text">{MAX_TOP_UP_MESSAGE}</span>
              )}
            </div>
            <div className="form-group">
              <label className="form-label">Payment Method</label>
              <select
                className="form-input"
                value={paymentMethod}
                onChange={(e) => setPaymentMethod(e.target.value)}
                required
              >
                <option value="JazzCash">JazzCash</option>
                <option value="EasyPaisa">EasyPaisa</option>
                <option value="Bank Transfer">Bank Transfer</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Transaction ID / Reference *</label>
              <input
                type="text"
                className="form-input"
                value={txnId}
                onChange={(e) => setTxnId(e.target.value)}
                placeholder="Your payment reference number"
                required
              />
            </div>
            <div className="form-group">
              <label className="form-label">Payment Proof (Screenshot) *</label>
              <input
                type="file"
                className="form-input"
                accept="image/*"
                onChange={(e) => setProofFile(e.target.files[0] || null)}
                required
              />
            </div>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? 'Submitting...' : 'Submit Top-Up Request'}
            </button>
          </form>
        </div>
      )}

      {/* Top-Up Requests */}
      {topUpRequests.length > 0 && (
        <section className="section">
          <h2 className="section-title">Top-Up Requests</h2>
          <div className="listings-table-wrap">
            <table className="listings-table">
              <thead>
                <tr>
                  <th>Amount</th>
                  <th>Method</th>
                  <th>Status</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {topUpRequests.map((req) => (
                  <tr key={req.id}>
                    <td className="listing-price">PKR {req.amount}</td>
                    <td>{req.payment_method || '—'}</td>
                    <td>
                      <span className={`status-pill status-${req.status === 'approved' ? 'active' : req.status === 'rejected' ? 'sold' : 'inactive'}`}>
                        {req.status === 'approved' ? '✅ Approved' : req.status === 'rejected' ? '❌ Rejected' : '⏳ Pending'}
                      </span>
                    </td>
                    <td>{new Date(req.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
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

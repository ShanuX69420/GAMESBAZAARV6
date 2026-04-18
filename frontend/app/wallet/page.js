'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getWallet, requestTopUp, getTopUpRequests } from '@/lib/api';

export default function WalletPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [walletData, setWalletData] = useState(null);
  const [topUpRequests, setTopUpRequests] = useState([]);
  const [showTopUp, setShowTopUp] = useState(false);
  const [topUpAmount, setTopUpAmount] = useState('');
  const [paymentMethod, setPaymentMethod] = useState('');
  const [txnId, setTxnId] = useState('');
  const [proofFile, setProofFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
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
        getWallet(),
        getTopUpRequests(),
      ]);
      setWalletData(wallet);
      setTopUpRequests(topups);
    } catch (err) {
      console.error(err);
    }
  }

  async function handleTopUp(e) {
    e.preventDefault();
    setError('');
    setSuccess('');
    setSubmitting(true);
    try {
      await requestTopUp(topUpAmount, paymentMethod, txnId, proofFile);
      setSuccess('Top-up request submitted! Admin will review it shortly.');
      setTopUpAmount('');
      setPaymentMethod('');
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
          <Link href="/orders" className="btn btn-outline">📦 My Orders</Link>
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
                onChange={(e) => setTopUpAmount(e.target.value)}
                placeholder="e.g. 1000"
                min="1"
                step="0.01"
                required
              />
            </div>
            <div className="form-group">
              <label className="form-label">Payment Method</label>
              <select
                className="form-input"
                value={paymentMethod}
                onChange={(e) => setPaymentMethod(e.target.value)}
              >
                <option value="">Select method...</option>
                <option value="JazzCash">JazzCash</option>
                <option value="EasyPaisa">EasyPaisa</option>
                <option value="Bank Transfer">Bank Transfer</option>
                <option value="Other">Other</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Transaction ID / Reference</label>
              <input
                type="text"
                className="form-input"
                value={txnId}
                onChange={(e) => setTxnId(e.target.value)}
                placeholder="Your payment reference number"
              />
            </div>
            <div className="form-group">
              <label className="form-label">Payment Proof (Screenshot)</label>
              <input
                type="file"
                className="form-input"
                accept="image/*"
                onChange={(e) => setProofFile(e.target.files[0] || null)}
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
                {walletData.transactions.map((txn) => (
                  <tr key={txn.id}>
                    <td>
                      <span className={`txn-type txn-${txn.transaction_type}`}>
                        {txn.transaction_type_display}
                      </span>
                    </td>
                    <td className={`txn-amount ${['purchase', 'commission'].includes(txn.transaction_type) ? 'txn-debit' : 'txn-credit'}`}>
                      {['purchase', 'commission'].includes(txn.transaction_type) ? '-' : '+'}PKR {txn.amount}
                    </td>
                    <td>PKR {txn.balance_after}</td>
                    <td className="txn-desc">{txn.description}</td>
                    <td>{new Date(txn.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
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

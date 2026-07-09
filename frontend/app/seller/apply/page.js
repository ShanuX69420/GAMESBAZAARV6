'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { getSellerStatus, applyAsSeller } from '@/lib/api';

export default function SellerApplyPage() {
  const { user, loading, fetchUser } = useAuth();
  const router = useRouter();
  const [sellerData, setSellerData] = useState(null);
  const [applicationNote, setApplicationNote] = useState('');
  const [applyError, setApplyError] = useState('');
  const [applying, setApplying] = useState(false);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (!loading && !user) {
      router.push('/login');
      return;
    }
    if (user) {
      if (user.is_seller) {
        router.replace('/dashboard');
        return;
      }
      getSellerStatus().then(setSellerData).catch(() => {});
    }
  }, [user, loading, router]);

  async function handleApply(e) {
    e.preventDefault();
    setApplyError('');
    setApplying(true);
    try {
      await applyAsSeller(applicationNote);
      await fetchUser();
      setSuccess(true);
    } catch (err) {
      setApplyError(err.message);
    } finally {
      setApplying(false);
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
      <div className="seller-apply-page">
        <div className="seller-apply-card">
          {success || sellerData?.seller_status === 'pending' ? (
            <div className="seller-apply-success">
              <div className="seller-apply-success-icon">⏳</div>
              <h1>Application Submitted!</h1>
              <p>Your seller application is under review. We&apos;ll notify you once it&apos;s been processed.</p>
              <p>Our team may message you here on GamesBazaar if we need more details (for example, a contact number for verification) — keep an eye on your inbox and email.</p>
              <Link href="/" className="btn btn-primary">Back to Home</Link>
            </div>
          ) : sellerData?.seller_status === 'rejected' ? (
            <div className="seller-apply-success">
              <div className="seller-apply-success-icon">❌</div>
              <h1>Application Rejected</h1>
              <p>Unfortunately your previous application was not approved. You can try applying again.</p>
              <form onSubmit={handleApply} style={{ width: '100%', maxWidth: '500px', marginTop: '20px' }}>
                {applyError && <div className="alert alert-error">{applyError}</div>}
                <div className="form-group">
                  <label className="form-label">Tell us about yourself</label>
                  <textarea
                    className="form-textarea"
                    value={applicationNote}
                    onChange={(e) => setApplicationNote(e.target.value)}
                    placeholder="What do you plan to sell? Any experience?"
                    rows={4}
                    required
                  />
                </div>
                <button type="submit" className="btn btn-primary btn-full" disabled={applying}>
                  {applying ? 'Submitting...' : 'Re-apply as Seller'}
                </button>
              </form>
            </div>
          ) : (
            <>
              <div className="seller-apply-header">
                <div className="seller-apply-icon">🏪</div>
                <h1>Become a Seller</h1>
                <p>Start selling digital gaming products on GamesBazaar and reach thousands of buyers.</p>
              </div>

              <div className="seller-apply-benefits">
                <div className="seller-benefit">
                  <span className="seller-benefit-icon">💰</span>
                  <div>
                    <strong>Earn Money</strong>
                    <p>Sell game accounts, items, and services to earn PKR</p>
                  </div>
                </div>
                <div className="seller-benefit">
                  <span className="seller-benefit-icon">📊</span>
                  <div>
                    <strong>Seller Dashboard</strong>
                    <p>Track your sales, revenue, and analytics in real-time</p>
                  </div>
                </div>
                <div className="seller-benefit">
                  <span className="seller-benefit-icon">⚡</span>
                  <div>
                    <strong>Auto Delivery</strong>
                    <p>Set up instant automated delivery for digital items</p>
                  </div>
                </div>
              </div>

              {applyError && <div className="alert alert-error">{applyError}</div>}

              <form onSubmit={handleApply} className="seller-apply-form">
                <div className="form-group">
                  <label className="form-label">Tell us about yourself *</label>
                  <textarea
                    className="form-textarea"
                    value={applicationNote}
                    onChange={(e) => setApplicationNote(e.target.value)}
                    placeholder="What games will you sell? Do you have experience selling digital items? Tell us anything relevant..."
                    rows={4}
                    required
                  />
                </div>
                <button type="submit" className="btn btn-primary btn-full" disabled={applying}>
                  {applying ? 'Submitting Application...' : 'Submit Seller Application'}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

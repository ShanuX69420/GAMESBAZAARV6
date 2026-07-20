'use client';

import { useState } from 'react';
import { submitReport } from '@/lib/api';
import { CheckCircleIcon } from '@/lib/icons';

const REPORT_REASONS = [
  { value: 'scam', label: 'Scam / Fraud', desc: 'Potential fraud or scam attempt' },
  { value: 'inappropriate', label: 'Inappropriate Content', desc: 'Offensive or inappropriate material' },
  { value: 'duplicate', label: 'Duplicate / Spam', desc: 'Duplicate listing or spam content' },
  { value: 'wrong_category', label: 'Wrong Category', desc: 'Listed in the wrong category' },
  { value: 'misleading', label: 'Misleading Information', desc: 'Inaccurate or deceptive details' },
  { value: 'harassment', label: 'Harassment / Abuse', desc: 'Harassment or abusive behavior' },
  { value: 'stolen', label: 'Stolen Account / Item', desc: 'Potentially stolen goods' },
  { value: 'other', label: 'Other', desc: 'Other reason not listed above' },
];

export default function ReportModal({ isOpen, onClose, targetType, listingId, userId, targetName }) {
  const [reason, setReason] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');

  if (!isOpen) return null;

  function handleOverlayClick(e) {
    if (e.target === e.currentTarget) onClose();
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!reason) {
      setError('Please select a reason for your report.');
      return;
    }
    setError('');
    setSubmitting(true);
    try {
      await submitReport({
        targetType,
        listingId: targetType === 'listing' ? listingId : undefined,
        userId: targetType === 'user' ? userId : undefined,
        reason,
        description,
      });
      setSuccess(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  function handleClose() {
    setReason('');
    setDescription('');
    setError('');
    setSuccess(false);
    onClose();
  }

  return (
    <div className="report-modal-overlay" onClick={handleOverlayClick}>
      <div className="report-modal">
        {/* Header */}
        <div className="report-modal-header">
          <div className="report-modal-header-left">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/>
              <line x1="4" y1="22" x2="4" y2="15"/>
            </svg>
            <h3>Report {targetType === 'listing' ? 'Listing' : 'User'}</h3>
          </div>
          <button className="report-modal-close" onClick={handleClose} aria-label="Close">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        {success ? (
          <div className="report-modal-success">
            <div className="report-success-icon"><CheckCircleIcon size={48} /></div>
            <h4>Report Submitted</h4>
            <p>Thank you for helping keep GamesBazaar safe. Our team will review your report and take appropriate action.</p>
            <button className="btn btn-primary" onClick={handleClose} style={{ marginTop: '16px' }}>
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            {/* Target info */}
            <div className="report-modal-target">
              <span className="report-target-label">Reporting:</span>
              <span className="report-target-name">{targetName || 'Unknown'}</span>
            </div>

            {/* Reason selection */}
            <div className="report-modal-section">
              <label className="report-section-label">Select a reason <span className="required">*</span></label>
              <div className="report-reasons-grid">
                {REPORT_REASONS.map((r) => (
                  <button
                    key={r.value}
                    type="button"
                    className={`report-reason-btn ${reason === r.value ? 'active' : ''}`}
                    onClick={() => { setReason(r.value); setError(''); }}
                  >
                    <span className="report-reason-label">{r.label}</span>
                    <span className="report-reason-desc">{r.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Description */}
            <div className="report-modal-section">
              <label className="report-section-label" htmlFor="report-desc">Additional details (optional)</label>
              <textarea
                id="report-desc"
                className="report-textarea"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Provide any additional context that would help us investigate..."
                maxLength={2000}
                rows={3}
              />
              <div className="report-char-count">{description.length}/2000</div>
            </div>

            {error && <div className="alert alert-error" style={{ marginBottom: '12px' }}>{error}</div>}

            <div className="report-modal-actions">
              <button type="button" className="btn btn-outline" onClick={handleClose}>Cancel</button>
              <button
                type="submit"
                className="btn btn-danger"
                disabled={submitting || !reason}
              >
                {submitting ? (
                  <><span className="loading-spinner" style={{ width: 14, height: 14 }} /> Submitting...</>
                ) : (
                  <>Submit Report</>
                )}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

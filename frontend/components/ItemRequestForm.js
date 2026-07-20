'use client';

import { useState } from 'react';
import { useAuth } from '@/lib/auth';
import { submitItemRequest } from '@/lib/api';
import { CheckCircleIcon } from '@/lib/icons';

export default function ItemRequestForm({ gameSlug, categorySlug, gameName, categoryName }) {
  const { user } = useAuth();
  const [message, setMessage] = useState('');
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (submitting || !message.trim()) return;
    setSubmitting(true);
    setError('');
    try {
      await submitItemRequest(gameSlug, categorySlug, message.trim(), email.trim());
      setSent(true);
    } catch (err) {
      setError(err.message || 'Failed to send your request. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  if (sent) {
    return (
      <div className="item-request-card item-request-card-sent">
        <div className="item-request-sent-icon"><CheckCircleIcon size={32} /></div>
        <h3 className="item-request-title">Request sent!</h3>
        <p className="item-request-sub">
          {user
            ? 'We’ll notify you as soon as it’s available.'
            : `We’ll email you at ${email.trim()} as soon as it’s available.`}
        </p>
      </div>
    );
  }

  return (
    <div className="item-request-card">
      <h3 className="item-request-title">Can&apos;t find what you need?</h3>
      <p className="item-request-sub">
        Tell us what you&apos;re looking for in {gameName} {categoryName} and
        we&apos;ll work on getting it for you.
      </p>
      <form onSubmit={handleSubmit} className="item-request-form">
        <textarea
          className="form-textarea"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="e.g., Level 60+ account with rare skins, budget around PKR 15,000"
          maxLength={2000}
          rows={3}
          required
        />
        {!user && (
          <input
            type="email"
            className="form-input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Your email — so we can let you know"
            required
          />
        )}
        {error && <p className="item-request-error">{error}</p>}
        <button
          type="submit"
          className="btn btn-primary"
          disabled={submitting || !message.trim()}
        >
          {submitting ? 'Sending...' : 'Request this item'}
        </button>
      </form>
    </div>
  );
}

'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/lib/auth';
import { submitSupportTicket, getMySupportTickets } from '@/lib/api';
import Link from 'next/link';

const FAQ_ITEMS = [
  {
    category: 'Buying',
    icon: '🛒',
    questions: [
      {
        q: 'How do I buy something on GamesBazaar?',
        a: 'Browse games, find a listing you like, click "Buy Now", and confirm the purchase. The payment is held securely until you receive and confirm your order. For categories with Buyer Protection, your funds stay held for an additional 14 days after confirmation — giving you a safety net to dispute any issues.',
      },
      {
        q: 'What if I don\'t receive my order?',
        a: 'If the seller hasn\'t delivered within the expected time, you can open a dispute from your order page. For protected orders, you can even dispute within 14 days after confirming delivery if something goes wrong (like account recovery by the original owner). Our team will investigate and resolve the issue — including a full refund if necessary.',
      },
      {
        q: 'Can I get a refund?',
        a: 'Yes! If the seller hasn\'t delivered or the item doesn\'t match the description, you can dispute the order. For orders with 14-Day Buyer Protection, you can still raise a dispute even after confirming delivery — the seller\'s payout is held for 14 days. If no protection applies, funds are released to the seller immediately upon confirmation.',
      },
    ],
  },
  {
    category: 'Selling',
    icon: '💰',
    questions: [
      {
        q: 'How do I become a seller?',
        a: 'Go to your Settings page and apply for a seller account. Tell us a bit about what you want to sell, and our team will review your application — usually within 24 hours.',
      },
      {
        q: 'How do I get paid?',
        a: 'When a buyer confirms an order, the payment (minus a small commission) is credited to your GamesBazaar wallet. You can then withdraw to your bank account, JazzCash, or EasyPaisa.',
      },
      {
        q: 'What commission does GamesBazaar charge?',
        a: 'Commission varies by category (typically 5-10%). You can see the exact rate for each category when creating a listing. The commission is automatically deducted when an order is completed.',
      },
    ],
  },
  {
    category: 'Payments & Wallet',
    icon: '💳',
    questions: [
      {
        q: 'How do I add funds to my wallet?',
        a: 'Go to your Wallet page, click "Add Funds", and message us on WhatsApp (0371 2101998) with the amount you want to add. We\'ll confirm the payment with you and credit your wallet within minutes.',
      },
      {
        q: 'How do I withdraw my earnings?',
        a: 'Go to your Wallet page and request a withdrawal (minimum PKR 500). Provide your account details and we\'ll process it within 1-2 business days.',
      },
      {
        q: 'Are my payments secure?',
        a: 'Absolutely. All payments are held securely until the buyer confirms delivery. For eligible categories, our 14-Day Buyer Protection adds another layer: funds remain held for 14 days after delivery confirmation. Neither the buyer nor the seller can access the funds during this period. After 14 days with no dispute, the funds are automatically released to the seller.',
      },
    ],
  },
  {
    category: 'Account',
    icon: '👤',
    questions: [
      {
        q: 'How do I change my username?',
        a: 'Go to Settings and update your username. Note: you can only change it once every 90 days.',
      },
      {
        q: 'How do I change my email?',
        a: 'Go to Settings and request an email change. We\'ll send verification codes to both your current and new email for security.',
      },
      {
        q: 'I forgot my password. What do I do?',
        a: 'Click "Forgot Password?" on the login page. We\'ll send a reset code to your registered email address.',
      },
    ],
  },
  {
    category: 'Safety',
    icon: '🛡️',
    questions: [
      {
        q: 'How do I report a scam or suspicious user?',
        a: 'You can report any listing or user directly from their profile or listing page. Click the report button and select a reason. Our team reviews all reports.',
      },
      {
        q: 'What should I do if someone asks me to trade outside GamesBazaar?',
        a: 'Never trade outside the platform. All transactions must go through GamesBazaar to ensure you\'re protected. Report anyone who suggests off-platform trading.',
      },
    ],
  },
];

const CATEGORY_OPTIONS = [
  { value: 'account', label: 'Account Issue', icon: '👤' },
  { value: 'order', label: 'Order Problem', icon: '📦' },
  { value: 'payment', label: 'Payment / Wallet', icon: '💳' },
  { value: 'seller', label: 'Seller Application', icon: '🏪' },
  { value: 'report', label: 'Report / Safety', icon: '🛡️' },
  { value: 'feedback', label: 'Feedback / Suggestion', icon: '💡' },
  { value: 'other', label: 'Other', icon: '📩' },
];

const STATUS_CONFIG = {
  open: { label: 'Open', className: 'ticket-status-open' },
  in_progress: { label: 'In Progress', className: 'ticket-status-progress' },
  resolved: { label: 'Resolved', className: 'ticket-status-resolved' },
  closed: { label: 'Closed', className: 'ticket-status-closed' },
};

export default function SupportPage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState('faq');
  const [openFaqCategory, setOpenFaqCategory] = useState(null);
  const [openQuestion, setOpenQuestion] = useState(null);

  // Form state
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    category: 'other',
    subject: '',
    message: '',
    orderId: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitSuccess, setSubmitSuccess] = useState(false);
  const [submitError, setSubmitError] = useState('');

  // Tickets state
  const [tickets, setTickets] = useState([]);
  const [ticketsLoading, setTicketsLoading] = useState(false);
  const [expandedTicket, setExpandedTicket] = useState(null);

  // Prefill name and email for logged-in users
  useEffect(() => {
    if (user) {
      setFormData((prev) => ({
        ...prev,
        name: user.username || '',
        email: user.email || '',
      }));
    }
  }, [user]);

  // Load tickets when tab changes
  useEffect(() => {
    if (activeTab === 'tickets' && user) {
      loadTickets();
    }
  }, [activeTab, user]);

  async function loadTickets() {
    setTicketsLoading(true);
    try {
      const data = await getMySupportTickets();
      setTickets(data.tickets || []);
    } catch {
      setTickets([]);
    } finally {
      setTicketsLoading(false);
    }
  }

  function handleChange(e) {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    setSubmitError('');
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!formData.subject.trim() || !formData.message.trim()) {
      setSubmitError('Please fill in the subject and message.');
      return;
    }
    if (!user && !formData.email.trim()) {
      setSubmitError('Please provide your email address so we can get back to you.');
      return;
    }

    setSubmitting(true);
    setSubmitError('');

    try {
      await submitSupportTicket({
        name: formData.name,
        email: formData.email,
        category: formData.category,
        subject: formData.subject,
        message: formData.message,
        orderId: formData.orderId ? parseInt(formData.orderId, 10) : null,
      });
      setSubmitSuccess(true);
      setFormData((prev) => ({
        ...prev,
        category: 'other',
        subject: '',
        message: '',
        orderId: '',
      }));
    } catch (err) {
      setSubmitError(err.message || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  function toggleFaqCategory(category) {
    setOpenFaqCategory(openFaqCategory === category ? null : category);
    setOpenQuestion(null);
  }

  function toggleQuestion(key) {
    setOpenQuestion(openQuestion === key ? null : key);
  }

  return (
    <div className="support-page container">
      {/* Header */}
      <div className="support-header">
        <div className="support-header-icon">💬</div>
        <h1>Help & Support</h1>
        <p className="support-subtitle">
          We&rsquo;re here to help. Find answers to common questions or reach out to our team directly.
        </p>
      </div>

      {/* Tab Navigation */}
      <div className="support-tabs">
        <button
          className={`support-tab ${activeTab === 'faq' ? 'active' : ''}`}
          onClick={() => setActiveTab('faq')}
          id="tab-faq"
        >
          <span className="support-tab-icon">❓</span>
          FAQs
        </button>
        <button
          className={`support-tab ${activeTab === 'contact' ? 'active' : ''}`}
          onClick={() => setActiveTab('contact')}
          id="tab-contact"
        >
          <span className="support-tab-icon">✉️</span>
          Contact Us
        </button>
        {user && (
          <button
            className={`support-tab ${activeTab === 'tickets' ? 'active' : ''}`}
            onClick={() => setActiveTab('tickets')}
            id="tab-tickets"
          >
            <span className="support-tab-icon">📋</span>
            My Tickets
          </button>
        )}
      </div>

      {/* FAQ Tab */}
      {activeTab === 'faq' && (
        <div className="support-faq-section">
          <p className="support-faq-intro">
            Browse our frequently asked questions by topic. Can&rsquo;t find what you&rsquo;re looking for?{' '}
            <button className="support-link-btn" onClick={() => setActiveTab('contact')}>
              Send us a message
            </button>.
          </p>

          <div className="support-faq-categories">
            {FAQ_ITEMS.map((faqCat) => (
              <div
                key={faqCat.category}
                className={`support-faq-category ${openFaqCategory === faqCat.category ? 'open' : ''}`}
              >
                <button
                  className="support-faq-category-header"
                  onClick={() => toggleFaqCategory(faqCat.category)}
                  aria-expanded={openFaqCategory === faqCat.category}
                >
                  <div className="support-faq-category-left">
                    <span className="support-faq-category-icon">{faqCat.icon}</span>
                    <span className="support-faq-category-name">{faqCat.category}</span>
                    <span className="support-faq-count">{faqCat.questions.length} questions</span>
                  </div>
                  <span className="support-faq-chevron">
                    {openFaqCategory === faqCat.category ? '▲' : '▼'}
                  </span>
                </button>

                {openFaqCategory === faqCat.category && (
                  <div className="support-faq-questions">
                    {faqCat.questions.map((item, idx) => {
                      const key = `${faqCat.category}-${idx}`;
                      return (
                        <div
                          key={key}
                          className={`support-faq-item ${openQuestion === key ? 'open' : ''}`}
                        >
                          <button
                            className="support-faq-question"
                            onClick={() => toggleQuestion(key)}
                            aria-expanded={openQuestion === key}
                          >
                            <span>{item.q}</span>
                            <span className="support-faq-toggle">
                              {openQuestion === key ? '−' : '+'}
                            </span>
                          </button>
                          {openQuestion === key && (
                            <div className="support-faq-answer">{item.a}</div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Contact Tab */}
      {activeTab === 'contact' && (
        <div className="support-contact-section">
          {submitSuccess ? (
            <div className="support-success-card">
              <div className="support-success-icon">✅</div>
              <h2>Ticket Submitted!</h2>
              <p>
                Thank you for reaching out. Our support team will review your message and get back to you
                {user ? ' through the platform' : ' via email'} as soon as possible — usually within 24 hours.
              </p>
              {user && (
                <p className="support-success-hint">
                  You can track the status of your ticket in the{' '}
                  <button className="support-link-btn" onClick={() => { setActiveTab('tickets'); setSubmitSuccess(false); }}>
                    My Tickets
                  </button>{' '}
                  tab.
                </p>
              )}
              <button
                className="support-btn-primary"
                onClick={() => setSubmitSuccess(false)}
              >
                Submit Another Ticket
              </button>
            </div>
          ) : (
            <>
              <div className="support-contact-intro">
                <div className="support-contact-info-cards">
                  <div className="support-info-card">
                    <span className="support-info-icon">⏰</span>
                    <div>
                      <strong>Response Time</strong>
                      <p>Usually within 24 hours</p>
                    </div>
                  </div>
                  <div className="support-info-card">
                    <span className="support-info-icon">📧</span>
                    <div>
                      <strong>Email</strong>
                      <p><a href="mailto:support@gamesbazaar.pk">support@gamesbazaar.pk</a></p>
                    </div>
                  </div>
                  <div className="support-info-card">
                    <span className="support-info-icon">📱</span>
                    <div>
                      <strong>Phone / WhatsApp</strong>
                      <p><a href="tel:+923712101998">+92 371 2101998</a></p>
                    </div>
                  </div>
                  <div className="support-info-card">
                    <span className="support-info-icon">🕐</span>
                    <div>
                      <strong>Hours</strong>
                      <p>Mon — Sat, 10 AM — 10 PM PKT</p>
                    </div>
                  </div>
                </div>
              </div>


              <form className="support-form" onSubmit={handleSubmit}>
                <h2 className="support-form-title">Send us a message</h2>

                {!user && (
                  <div className="support-form-row">
                    <div className="support-form-group">
                      <label htmlFor="support-name">Your Name</label>
                      <input
                        id="support-name"
                        name="name"
                        type="text"
                        placeholder="Enter your name"
                        value={formData.name}
                        onChange={handleChange}
                        maxLength={200}
                      />
                    </div>
                    <div className="support-form-group">
                      <label htmlFor="support-email">
                        Email Address <span className="support-required">*</span>
                      </label>
                      <input
                        id="support-email"
                        name="email"
                        type="email"
                        placeholder="your@email.com"
                        value={formData.email}
                        onChange={handleChange}
                        required
                      />
                    </div>
                  </div>
                )}

                <div className="support-form-row">
                  <div className="support-form-group">
                    <label htmlFor="support-category">Category</label>
                    <select
                      id="support-category"
                      name="category"
                      value={formData.category}
                      onChange={handleChange}
                    >
                      {CATEGORY_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.icon} {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  {(formData.category === 'order') && (
                    <div className="support-form-group">
                      <label htmlFor="support-order-id">Order ID (optional)</label>
                      <input
                        id="support-order-id"
                        name="orderId"
                        type="number"
                        placeholder="e.g. 1234"
                        value={formData.orderId}
                        onChange={handleChange}
                        min="1"
                      />
                    </div>
                  )}
                </div>

                <div className="support-form-group">
                  <label htmlFor="support-subject">
                    Subject <span className="support-required">*</span>
                  </label>
                  <input
                    id="support-subject"
                    name="subject"
                    type="text"
                    placeholder="Brief summary of your issue"
                    value={formData.subject}
                    onChange={handleChange}
                    required
                    maxLength={300}
                  />
                </div>

                <div className="support-form-group">
                  <label htmlFor="support-message">
                    Message <span className="support-required">*</span>
                  </label>
                  <textarea
                    id="support-message"
                    name="message"
                    placeholder="Please describe your issue in detail. Include any relevant information like order numbers, usernames, or screenshots."
                    value={formData.message}
                    onChange={handleChange}
                    required
                    maxLength={5000}
                    rows={6}
                  />
                  <div className="support-char-count">
                    {formData.message.length} / 5000
                  </div>
                </div>

                {submitError && (
                  <div className="support-error">{submitError}</div>
                )}

                <button
                  type="submit"
                  className="support-btn-primary support-submit-btn"
                  disabled={submitting}
                >
                  {submitting ? 'Submitting...' : '📨 Submit Ticket'}
                </button>
              </form>
            </>
          )}
        </div>
      )}

      {/* My Tickets Tab */}
      {activeTab === 'tickets' && user && (
        <div className="support-tickets-section">
          {ticketsLoading ? (
            <div className="support-loading">Loading your tickets...</div>
          ) : tickets.length === 0 ? (
            <div className="support-empty">
              <div className="support-empty-icon">📭</div>
              <h3>No tickets yet</h3>
              <p>You haven&rsquo;t submitted any support tickets. If you need help, we&rsquo;re just a click away.</p>
              <button
                className="support-btn-primary"
                onClick={() => setActiveTab('contact')}
              >
                Contact Support
              </button>
            </div>
          ) : (
            <div className="support-tickets-list">
              {tickets.map((ticket) => {
                const statusCfg = STATUS_CONFIG[ticket.status] || STATUS_CONFIG.open;
                const isExpanded = expandedTicket === ticket.id;
                return (
                  <div
                    key={ticket.id}
                    className={`support-ticket-card ${isExpanded ? 'expanded' : ''}`}
                  >
                    <button
                      className="support-ticket-header"
                      onClick={() => setExpandedTicket(isExpanded ? null : ticket.id)}
                    >
                      <div className="support-ticket-left">
                        <span className={`support-ticket-status ${statusCfg.className}`}>
                          {statusCfg.label}
                        </span>
                        <span className="support-ticket-subject">{ticket.subject}</span>
                      </div>
                      <div className="support-ticket-right">
                        <span className="support-ticket-category">{ticket.category_display}</span>
                        <span className="support-ticket-date">
                          {new Date(ticket.created_at).toLocaleDateString('en-PK', {
                            day: 'numeric', month: 'short', year: 'numeric',
                          })}
                        </span>
                        <span className="support-faq-chevron">{isExpanded ? '▲' : '▼'}</span>
                      </div>
                    </button>

                    {isExpanded && (
                      <div className="support-ticket-body">
                        <div className="support-ticket-message">
                          <strong>Your message:</strong>
                          <p>{ticket.message}</p>
                        </div>
                        {ticket.order_id && (
                          <div className="support-ticket-meta">
                            <strong>Related Order:</strong> #{ticket.order_id}
                          </div>
                        )}
                        {ticket.admin_reply ? (
                          <div className="support-ticket-reply">
                            <div className="support-ticket-reply-header">
                              <span>💬</span>
                              <strong>GamesBazaar Support</strong>
                            </div>
                            <p>{ticket.admin_reply}</p>
                          </div>
                        ) : (
                          <div className="support-ticket-pending-reply">
                            <span>⏳</span> Awaiting response from our team
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Bottom Links */}
      <div className="support-bottom-links">
        <p>You can also check our policies:</p>
        <div className="support-policy-links">
          <Link href="/privacy-policy" className="support-policy-link">
            🔒 Privacy Policy
          </Link>
          <Link href="/terms-of-service" className="support-policy-link">
            📜 Terms of Service
          </Link>
        </div>
      </div>
    </div>
  );
}

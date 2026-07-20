import Link from 'next/link';

export const metadata = {
  title: 'Page Not Found — GamesBazaar',
  description: 'The page you are looking for does not exist or has been moved.',
};

export default function NotFound() {
  return (
    <div className="container">
      <div className="error-page">
        <div className="error-visual">
          <div className="error-code-display">
            <span className="error-digit">4</span>
            <span className="error-digit error-digit-accent">
              <svg width="80" height="80" viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="40" cy="40" r="36" stroke="currentColor" strokeWidth="4" strokeDasharray="6 6" />
                <circle cx="30" cy="34" r="4" fill="currentColor" />
                <circle cx="50" cy="34" r="4" fill="currentColor" />
                <path d="M28 52c4-6 20-6 24 0" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
              </svg>
            </span>
            <span className="error-digit">4</span>
          </div>
        </div>

        <h1 className="error-title">Page not found</h1>
        <p className="error-description">
          The page you&apos;re looking for doesn&apos;t exist, was removed, or the URL might be wrong.
        </p>

        <div className="error-actions">
          <Link href="/" className="btn btn-primary error-btn-home">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
            Back to Home
          </Link>
          <Link href="/support" className="btn btn-outline error-btn-support">
            Contact Support
          </Link>
        </div>

        <div className="error-suggestions">
          <p className="error-suggestions-title">You might be looking for:</p>
          <div className="error-suggestion-links">
            <Link href="/" className="error-suggestion-chip">Games</Link>
            <Link href="/inbox" className="error-suggestion-chip">Inbox</Link>
            <Link href="/orders" className="error-suggestion-chip">My Orders</Link>
            <Link href="/wallet" className="error-suggestion-chip">Wallet</Link>
            <Link href="/support" className="error-suggestion-chip">Support</Link>
          </div>
        </div>
      </div>
    </div>
  );
}

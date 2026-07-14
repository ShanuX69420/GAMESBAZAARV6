import Link from 'next/link';

export default function Footer() {
  return (
    <footer className="footer">
      <div className="container">
        {/* Top Section */}
        <div className="footer-top">
          {/* Brand */}
          <div className="footer-brand">
            <div className="footer-brand-name">
              <img
                src="/icons/icon-72x72.png"
                alt=""
                className="footer-brand-logo"
                width="28"
                height="28"
                loading="lazy"
              />
              GamesBazaar
            </div>
            <p className="footer-brand-tagline">
              Pakistan&apos;s trusted marketplace for buying &amp; selling game accounts, items, and services.
            </p>
          </div>

          {/* Quick Links */}
          <div>
            <div className="footer-nav-title">Quick Links</div>
            <ul className="footer-links">
              <li><Link href="/">Home</Link></li>
              <li><Link href="/games">Games</Link></li>
              <li><Link href="/support">Support</Link></li>
            </ul>
          </div>

          {/* Contact */}
          <div>
            <div className="footer-nav-title">Contact</div>
            <ul className="footer-links">
              <li><a href="mailto:support@gamesbazaar.pk">support@gamesbazaar.pk</a></li>
              <li><a href="tel:+923712101998">+92 371 2101998</a></li>
            </ul>
          </div>

          {/* Social */}
          <div className="footer-social">
            <div className="footer-nav-title">Follow Us</div>
            <div className="footer-social-icons">
              <a
                href="https://instagram.com"
                target="_blank"
                rel="noopener noreferrer"
                className="footer-social-link"
                aria-label="Follow us on Instagram"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="2" y="2" width="20" height="20" rx="5" ry="5"/>
                  <path d="M16 11.37A4 4 0 1112.63 8 4 4 0 0116 11.37z"/>
                  <line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/>
                </svg>
              </a>
              <a
                href="https://facebook.com"
                target="_blank"
                rel="noopener noreferrer"
                className="footer-social-link"
                aria-label="Follow us on Facebook"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M18 2h-3a5 5 0 00-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 011-1h3z"/>
                </svg>
              </a>
            </div>
          </div>
        </div>

        {/* Bottom Section */}
        <div className="footer-bottom">
          <div className="footer-copy">
            &copy; {new Date().getFullYear()} GamesBazaar. All rights reserved.
          </div>
          <ul className="footer-legal">
            <li><Link href="/privacy-policy">Privacy Policy</Link></li>
            <li><Link href="/terms-of-service">Terms of Service</Link></li>
          </ul>
        </div>
      </div>
    </footer>
  );
}

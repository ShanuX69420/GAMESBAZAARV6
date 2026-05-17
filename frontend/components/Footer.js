import Link from 'next/link';

export default function Footer() {
  return (
    <footer className="footer">
      <div className="container footer-inner">
        <div className="footer-brand"><img src="/logo.png" alt="GamesBazaar" className="footer-brand-logo" loading="lazy" /> GamesBazaar</div>
        <ul className="footer-links">
          <li><Link href="/">Home</Link></li>
          <li><Link href="/support">Support</Link></li>
          <li><Link href="/privacy-policy">Privacy Policy</Link></li>
          <li><Link href="/terms-of-service">Terms of Service</Link></li>
        </ul>
        <div className="footer-copy">
          &copy; {new Date().getFullYear()} GamesBazaar. All rights reserved.
        </div>
      </div>
    </footer>
  );
}

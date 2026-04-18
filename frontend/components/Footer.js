import Link from 'next/link';

export default function Footer() {
  return (
    <footer className="footer">
      <div className="container footer-inner">
        <div className="footer-brand">🎮 GamesBazaar</div>
        <ul className="footer-links">
          <li><Link href="/">Home</Link></li>
          <li><Link href="/">About</Link></li>
          <li><Link href="/">Support</Link></li>
        </ul>
        <div className="footer-copy">
          &copy; {new Date().getFullYear()} GamesBazaar. All rights reserved.
        </div>
      </div>
    </footer>
  );
}

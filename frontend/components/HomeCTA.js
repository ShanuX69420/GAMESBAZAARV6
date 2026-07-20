'use client';

import { useAuth } from '@/lib/auth';
import Link from 'next/link';

export default function HomeCTA() {
  const { user } = useAuth();

  // Rendered during the auth check so guests (the common case, and every
  // CrUX-measured first visit) get it in the server HTML instead of having
  // it pop in later and shift the footer — that pop-in was a real mobile CLS
  // hit. Logged-in users don't see it flash on refresh: the pre-paint auth
  // hint (html[data-auth-hint="1"], see app/layout.js) hides it via CSS
  // before first paint, and it unmounts here once the auth check confirms.
  if (user) return null;

  return (
    <section className="home-cta">
      <h2>Ready to start trading?</h2>
      <p>Join Pakistan&apos;s first gaming marketplace — 5,000+ live listings across 300+ games.</p>
      <div className="home-cta-actions">
        <Link href="/register" className="btn btn-primary btn-lg">Create Account</Link>
        <Link href="/login" className="btn btn-outline btn-lg">Sign In</Link>
      </div>
    </section>
  );
}

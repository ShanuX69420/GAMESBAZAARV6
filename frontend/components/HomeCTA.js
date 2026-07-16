'use client';

import { useAuth } from '@/lib/auth';
import Link from 'next/link';

export default function HomeCTA() {
  const { user, loading } = useAuth();

  // Wait for the auth check so logged-in users don't see this flash on refresh.
  if (loading || user) return null;

  return (
    <section className="home-cta">
      <h2>Ready to start trading?</h2>
      <p>Join thousands of gamers buying and selling on GamesBazaar.</p>
      <div className="home-cta-actions">
        <Link href="/register" className="btn btn-primary btn-lg">Create Account</Link>
        <Link href="/login" className="btn btn-outline btn-lg">Sign In</Link>
      </div>
    </section>
  );
}

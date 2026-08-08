import { createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'Login',
    description: 'Sign in to your GamesBazaar account to buy, sell, and trade game items securely.',
    path: '/login',
    // Nothing here is worth ranking for, and it competes with the real landing
    // pages. Still followed so the nav links keep passing crawl signal.
    robots: { index: false, follow: true },
  }),
};

export default function LoginLayout({ children }) {
  return children;
}

import { createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'Create Account',
    description: 'Join Pakistan\'s first digital gaming marketplace. Create your free account to start buying and selling game items.',
    path: '/register',
    // Nothing here is worth ranking for, and it competes with the real landing
    // pages. Still followed so the nav links keep passing crawl signal.
    robots: { index: false, follow: true },
  }),
};

export default function RegisterLayout({ children }) {
  return children;
}

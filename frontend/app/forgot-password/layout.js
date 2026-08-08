import { createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'Reset Password',
    description: 'Reset your GamesBazaar account password securely.',
    path: '/forgot-password',
    // Nothing here is worth ranking for, and it competes with the real landing
    // pages. Still followed so the nav links keep passing crawl signal.
    robots: { index: false, follow: true },
  }),
};

export default function ForgotPasswordLayout({ children }) {
  return children;
}

import { createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'Verify Email',
    description: 'Enter the verification code we sent to your email to activate your GamesBazaar account.',
    path: '/verify-email',
    // Mid-signup step — nothing here is worth ranking for.
    robots: { index: false, follow: true },
  }),
};

export default function VerifyEmailLayout({ children }) {
  return children;
}

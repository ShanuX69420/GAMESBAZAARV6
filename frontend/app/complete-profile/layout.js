import { createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'Complete Your Profile',
    description: 'Pick a username to finish setting up your GamesBazaar account.',
    path: '/complete-profile',
    // Mid-signup step — nothing here is worth ranking for.
    robots: { index: false, follow: true },
  }),
};

export default function CompleteProfileLayout({ children }) {
  return children;
}

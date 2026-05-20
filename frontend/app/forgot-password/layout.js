import { createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'Reset Password',
    description: 'Reset your GamesBazaar account password securely.',
    path: '/forgot-password',
  }),
};

export default function ForgotPasswordLayout({ children }) {
  return children;
}

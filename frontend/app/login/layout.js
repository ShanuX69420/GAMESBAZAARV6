import { createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'Login',
    description: 'Sign in to your GamesBazaar account to buy, sell, and trade game items securely.',
    path: '/login',
  }),
};

export default function LoginLayout({ children }) {
  return children;
}

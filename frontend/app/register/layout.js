import { createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'Create Account',
    description: 'Join Pakistan\'s #1 digital gaming marketplace. Create your free account to start buying and selling game items.',
    path: '/register',
  }),
};

export default function RegisterLayout({ children }) {
  return children;
}

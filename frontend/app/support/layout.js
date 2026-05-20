import { createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'Help & Support',
    description: 'Get help with your orders, payments, or account. Browse FAQs or contact GamesBazaar support directly.',
    path: '/support',
  }),
};

export default function SupportLayout({ children }) {
  return children;
}

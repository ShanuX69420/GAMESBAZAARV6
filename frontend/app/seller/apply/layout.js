import { createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'Become a Seller',
    description: 'Apply to become a verified seller on GamesBazaar and start earning by selling game items, accounts, and services.',
    path: '/seller/apply',
  }),
};

export default function SellerApplyLayout({ children }) {
  return children;
}

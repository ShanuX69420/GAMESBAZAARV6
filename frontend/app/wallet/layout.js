import { privatePageRobots } from '@/lib/metadata';

export const metadata = {
  title: 'Wallet',
  description: 'Manage your wallet balance, top-ups, and withdrawals on GamesBazaar.',
  robots: privatePageRobots,
};

export default function WalletLayout({ children }) {
  return children;
}

import { privatePageRobots } from '@/lib/metadata';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'My Listings',
  description: 'Manage your active, inactive, and sold listings on GamesBazaar.',
  robots: privatePageRobots,
};

export default function MyListingsLayout({ children }) {
  return children;
}

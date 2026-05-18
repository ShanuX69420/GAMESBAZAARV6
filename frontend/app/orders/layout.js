import { privatePageRobots } from '@/lib/metadata';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'My Orders',
  description: 'Track and manage your purchases on GamesBazaar.',
  robots: privatePageRobots,
};

export default function OrdersLayout({ children }) {
  return children;
}

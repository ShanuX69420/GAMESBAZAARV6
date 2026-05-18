import { privatePageRobots } from '@/lib/metadata';

export const metadata = {
  title: 'My Sales',
  description: 'Manage your sales, track orders, and view revenue on GamesBazaar.',
  robots: privatePageRobots,
};

export default function SalesLayout({ children }) {
  return children;
}

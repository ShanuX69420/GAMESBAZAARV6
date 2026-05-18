import { privatePageRobots } from '@/lib/metadata';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'Seller Dashboard',
  description: 'View your sales analytics, revenue, and listing performance on GamesBazaar.',
  robots: privatePageRobots,
};

export default function DashboardLayout({ children }) {
  return children;
}

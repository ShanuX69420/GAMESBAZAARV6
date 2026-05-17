import { privatePageRobots } from '@/lib/metadata';

export const metadata = {
  title: 'Order Details',
  description: 'View and manage your GamesBazaar order.',
  robots: privatePageRobots,
};

export default function OrderDetailLayout({ children }) {
  return children;
}

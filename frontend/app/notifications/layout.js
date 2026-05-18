import { privatePageRobots } from '@/lib/metadata';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'Notifications',
  description: 'View your latest notifications and updates on GamesBazaar.',
  robots: privatePageRobots,
};

export default function NotificationsLayout({ children }) {
  return children;
}

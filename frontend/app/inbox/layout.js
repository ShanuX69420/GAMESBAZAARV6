import { privatePageRobots } from '@/lib/metadata';

export const metadata = {
  title: 'Inbox',
  description: 'View your conversations with buyers and sellers on GamesBazaar.',
  robots: privatePageRobots,
};

export default function InboxLayout({ children }) {
  return children;
}

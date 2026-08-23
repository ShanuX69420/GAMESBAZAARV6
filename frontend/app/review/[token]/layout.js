import { privatePageRobots } from '@/lib/metadata';

export const metadata = {
  title: 'Leave a Review',
  description: 'Tell us how your GamesBazaar purchase went.',
  robots: privatePageRobots,
};

export default function ReviewLinkLayout({ children }) {
  return children;
}

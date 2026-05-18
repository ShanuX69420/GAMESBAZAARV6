import { privatePageRobots } from '@/lib/metadata';

export const metadata = {
  title: 'Account Settings',
  description: 'Update your profile, change your password, and manage your GamesBazaar account settings.',
  robots: privatePageRobots,
};

export default function SettingsLayout({ children }) {
  return children;
}

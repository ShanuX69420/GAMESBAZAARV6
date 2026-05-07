import './globals.css';
import './reviews.css';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import { AuthProvider } from '@/lib/auth';

export const metadata = {
  title: 'GamesBazaar — Pakistan\'s #1 Digital Gaming Marketplace',
  description: 'Buy & sell game accounts, top-ups, items, and boosting services. Pakistan\'s trusted gaming marketplace.',
  icons: {
    icon: '/logo.png',
    apple: '/logo.png',
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <Navbar />
          <main>{children}</main>
          <Footer />
        </AuthProvider>
      </body>
    </html>
  );
}

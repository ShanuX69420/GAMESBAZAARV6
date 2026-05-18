import './globals.css';
import './reviews.css';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import { AuthProvider } from '@/lib/auth';

export const metadata = {
  title: {
    default: 'GamesBazaar — Pakistan\'s #1 Digital Gaming Marketplace',
    template: '%s | GamesBazaar',
  },
  description: 'Buy & sell game accounts, top-ups, items, and boosting services. Pakistan\'s trusted gaming marketplace with secure payments and verified sellers.',
  manifest: '/manifest.json',
  icons: {
    icon: '/icons/icon-96x96.png',
    apple: '/apple-touch-icon.png',
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'GamesBazaar',
  },
  openGraph: {
    type: 'website',
    locale: 'en_US',
    siteName: 'GamesBazaar',
    title: 'GamesBazaar — Pakistan\'s #1 Digital Gaming Marketplace',
    description: 'Buy & sell game accounts, top-ups, items, and boosting services. Secure payments, verified sellers, and fast delivery.',
  },
  robots: {
    index: true,
    follow: true,
  },
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000'),
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

import { createPublicMetadata, faqPageJsonLd } from '@/lib/seo';
import JsonLd from '@/components/JsonLd';
import { FAQ_ITEMS } from './faqData';

export const metadata = {
  ...createPublicMetadata({
    title: 'Help & Support',
    description: 'Get help with your orders, payments, or account. Browse FAQs or contact GamesBazaar support directly.',
    path: '/support',
  }),
};

export default function SupportLayout({ children }) {
  return (
    <>
      <JsonLd data={faqPageJsonLd(FAQ_ITEMS)} />
      {children}
    </>
  );
}

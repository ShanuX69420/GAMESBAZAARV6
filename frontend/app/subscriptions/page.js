import CategorySectionPage from '@/components/CategorySectionPage';
import { createPublicMetadata } from '@/lib/seo';
import { getCategorySection } from '@/lib/categorySections';

const section = getCategorySection('subscriptions');

export const metadata = {
  ...createPublicMetadata({
    title: section.title,
    description: section.description,
    path: `/${section.slug}`,
  }),
};

export default function AllSubscriptionsPage() {
  return <CategorySectionPage section={section} />;
}

import CategorySectionPage from '@/components/CategorySectionPage';
import { createPublicMetadata } from '@/lib/seo';
import { getCategorySection } from '@/lib/categorySections';

const section = getCategorySection('keys');

export const metadata = {
  ...createPublicMetadata({
    title: section.title,
    description: section.description,
    path: `/${section.slug}`,
  }),
};

export default async function AllKeysPage({ searchParams }) {
  const query = await searchParams;
  const method = typeof query?.method === 'string' ? query.method : '';
  const region = typeof query?.region === 'string' ? query.region : '';
  return <CategorySectionPage section={section} method={method} region={region} />;
}

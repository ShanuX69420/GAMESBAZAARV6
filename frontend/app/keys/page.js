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

// No searchParams: reading them made this the one section page Next had to
// render per request (no-store, ~0.5 s of server time on the 1-vCPU box while
// /accounts and friends were served prerendered). ?method=/?region=/?sort= are
// applied in the browser instead — see components/SectionGameList.js.
export default function AllKeysPage() {
  return <CategorySectionPage section={section} />;
}

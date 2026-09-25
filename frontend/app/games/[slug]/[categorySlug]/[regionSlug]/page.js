import { notFound } from 'next/navigation';
import CategorySeoText from '@/components/CategorySeoText';
import { categoryPageApiUrl, fetchCategoryPage } from '@/lib/categoryPageSeo';
import GameCategoryClient from '../GameCategoryClient';

// An allow-listed region page: the game+category page with its Region
// filter pinned (/games/playstation/gift-cards/usa). The backend only
// answers for regions on the allow-list (CategoryRegionPage rows, seeded
// from seo_copy.json), so anything else is a plain 404 — never a thin
// auto-generated page for every region in the dropdown. Metadata + JSON-LD
// live in ./layout.js.
//
// Cached the same way as the brand page (see ../(brand)/page.js): no
// request-time reads, generateStaticParams present, ?option=/?method=
// applied by GameCategoryClient after mount.
export async function generateStaticParams() {
  return [];
}

async function fetchInitialRegionData({ slug, categorySlug, regionSlug }) {
  const res = await fetchCategoryPage(categoryPageApiUrl({ slug, categorySlug, regionSlug }));
  if (res.status === 404) notFound();
  if (!res.ok) throw new Error('Failed to fetch game category region');
  return res.json();
}

export default async function GameCategoryRegionPage({ params }) {
  const { slug, categorySlug, regionSlug } = await params;
  const initialData = await fetchInitialRegionData({ slug, categorySlug, regionSlug });

  // Renamed-page twins are redirected by ./layout.js (a real 308).
  return (
    <>
      <GameCategoryClient initialData={initialData} />
      <CategorySeoText text={initialData?.seo_body} />
    </>
  );
}

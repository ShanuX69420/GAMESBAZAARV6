import { API_BASE } from '@/lib/config';
import { getSiteUrl } from '@/lib/seo';

const SITEMAP_REVALIDATE_SECONDS = 3600;

function categorySlugFromGameCategory(gameCategory) {
  return (
    gameCategory?.category?.slug ||
    gameCategory?.category_slug ||
    gameCategory?.slug ||
    ''
  );
}

function pageUrl(siteUrl, path) {
  return `${siteUrl}${path === '/' ? '' : path}`;
}

async function fetchGameCategories(gameSlug) {
  const res = await fetch(`${API_BASE}/api/games/${encodeURIComponent(gameSlug)}/`, {
    next: { revalidate: SITEMAP_REVALIDATE_SECONDS },
  });
  if (!res.ok) return [];

  const game = await res.json();
  return game.categories || [];
}

export default async function sitemap() {
  const siteUrl = getSiteUrl();

  const staticPages = [
    { url: pageUrl(siteUrl, '/'), changeFrequency: 'daily', priority: 1.0 },
    { url: pageUrl(siteUrl, '/games'), changeFrequency: 'daily', priority: 0.9 },
    { url: pageUrl(siteUrl, '/login'), changeFrequency: 'monthly', priority: 0.3 },
    { url: pageUrl(siteUrl, '/register'), changeFrequency: 'monthly', priority: 0.3 },
    { url: pageUrl(siteUrl, '/support'), changeFrequency: 'monthly', priority: 0.4 },
    { url: pageUrl(siteUrl, '/privacy-policy'), changeFrequency: 'yearly', priority: 0.2 },
    { url: pageUrl(siteUrl, '/terms-of-service'), changeFrequency: 'yearly', priority: 0.2 },
  ];

  let gamePages = [];
  try {
    const res = await fetch(`${API_BASE}/api/games/`, { next: { revalidate: SITEMAP_REVALIDATE_SECONDS } });
    if (res.ok) {
      const games = await res.json();
      for (const game of games) {
        const categories = (game.categories || []).length
          ? game.categories
          : await fetchGameCategories(game.slug);
        const categorySlugs = [...new Set(categories
          .map(categorySlugFromGameCategory)
          .filter(Boolean))];

        if (categorySlugs.length > 0) {
          for (const categorySlug of categorySlugs) {
            gamePages.push({
              url: pageUrl(siteUrl, `/games/${game.slug}/${categorySlug}`),
              changeFrequency: 'daily',
              priority: 0.7,
            });
          }
        } else {
          gamePages.push({
            url: pageUrl(siteUrl, `/games/${game.slug}`),
            changeFrequency: 'weekly',
            priority: 0.8,
          });
        }
      }
    }
  } catch {
    // Static pages still give crawlers a valid sitemap if the API is down.
  }

  return [...staticPages, ...gamePages];
}

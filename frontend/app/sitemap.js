import { API_BASE } from '@/lib/config';

export default async function sitemap() {
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000';

  // Static pages
  const staticPages = [
    { url: siteUrl, changeFrequency: 'daily', priority: 1.0 },
    { url: `${siteUrl}/games`, changeFrequency: 'daily', priority: 0.9 },
    { url: `${siteUrl}/login`, changeFrequency: 'monthly', priority: 0.3 },
    { url: `${siteUrl}/register`, changeFrequency: 'monthly', priority: 0.3 },
    { url: `${siteUrl}/support`, changeFrequency: 'monthly', priority: 0.4 },
    { url: `${siteUrl}/privacy-policy`, changeFrequency: 'yearly', priority: 0.2 },
    { url: `${siteUrl}/terms-of-service`, changeFrequency: 'yearly', priority: 0.2 },
  ];

  // Dynamic: games and game categories
  let gamePages = [];
  try {
    const res = await fetch(`${API_BASE}/api/games/`, { next: { revalidate: 3600 } });
    if (res.ok) {
      const games = await res.json();
      for (const game of games) {
        gamePages.push({
          url: `${siteUrl}/games/${game.slug}`,
          changeFrequency: 'weekly',
          priority: 0.8,
        });
        if (game.categories) {
          for (const gc of game.categories) {
            gamePages.push({
              url: `${siteUrl}/games/${game.slug}/${gc.category.slug}`,
              changeFrequency: 'daily',
              priority: 0.7,
            });
          }
        }
      }
    }
  } catch {
    // Fail silently — sitemap will just have static pages
  }

  return [...staticPages, ...gamePages];
}

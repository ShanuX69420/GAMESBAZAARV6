function titleFromSlug(value, fallback) {
  const text = String(value || '')
    .replace(/[-_+]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!text) return fallback;

  return text.replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

export async function generateMetadata({ params }) {
  const { slug, categorySlug } = await params;
  const gameName = titleFromSlug(slug, 'Game');
  const categoryName = titleFromSlug(categorySlug, 'Listings');
  const title = `${gameName} ${categoryName} Listings`;
  const description = `Browse ${gameName} ${categoryName} listings on GamesBazaar. Compare prices from verified sellers with buyer protection.`;

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      type: 'website',
      siteName: 'GamesBazaar',
    },
  };
}

export default function GameCategoryLayout({ children }) {
  return children;
}

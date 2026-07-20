import Link from 'next/link';

export default function CategoryCard({ gameSlug, category }) {
  return (
    <Link
      href={`/games/${gameSlug}/${category.slug}`}
      className="category-card"
    >
      <div className="category-name">{category.name}</div>
      {category.description && (
        <div className="category-desc">{category.description}</div>
      )}
    </Link>
  );
}

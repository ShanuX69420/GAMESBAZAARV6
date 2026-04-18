import { fetchGame } from '@/lib/api';
import { getGameIcon } from '@/lib/icons';
import CategoryCard from '@/components/CategoryCard';
import { notFound } from 'next/navigation';

export async function generateMetadata({ params }) {
  const { slug } = await params;
  try {
    const game = await fetchGame(slug);
    return {
      title: `${game.name} — GamesBazaar`,
      description: game.description || `Buy & sell ${game.name} accounts, items, and services on GamesBazaar.`,
    };
  } catch {
    return { title: 'Game Not Found — GamesBazaar' };
  }
}

export default async function GameDetailPage({ params }) {
  const { slug } = await params;
  let game;

  try {
    game = await fetchGame(slug);
  } catch {
    notFound();
  }

  const categories = game.categories || [];

  return (
    <div className="container">
      {/* Page Header */}
      <div className="page-header">
        <div className="breadcrumb">
          <a href="/">Home</a>
          <span className="breadcrumb-sep">›</span>
          <span>{game.name}</span>
        </div>

        <div className="game-header">
          <div className="game-header-icon">
            {game.icon_url ? (
              <img src={game.icon_url} alt={game.name} />
            ) : (
              getGameIcon(slug)
            )}
          </div>
          <div className="game-header-info">
            <h1>{game.name}</h1>
            {game.description && <p>{game.description}</p>}
          </div>
        </div>
      </div>

      {/* Categories */}
      <section className="section">
        <div className="section-header">
          <h2 className="section-title">Categories</h2>
        </div>

        {categories.length > 0 ? (
          <div className="categories-grid">
            {categories.map((gc) => (
              <CategoryCard
                key={gc.id}
                gameSlug={slug}
                category={gc.category}
              />
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon">📦</div>
            <p>No categories available for this game yet.</p>
          </div>
        )}
      </section>
    </div>
  );
}

import { fetchGame } from '@/lib/api';
import { createPublicMetadata } from '@/lib/seo';
import Image from 'next/image';
import { redirect, notFound } from 'next/navigation';

export async function generateMetadata({ params }) {
  const { slug } = await params;
  try {
    const game = await fetchGame(slug);
    return createPublicMetadata({
      title: game.name,
      description: game.description || `Buy & sell ${game.name} accounts, items, and services on GamesBazaar.`,
      path: `/games/${encodeURIComponent(slug)}`,
    });
  } catch {
    return createPublicMetadata({
      title: 'Game Not Found',
      description: 'This GamesBazaar game page could not be found.',
      path: `/games/${encodeURIComponent(slug)}`,
      robots: {
        index: false,
        follow: false,
      },
    });
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

  // Redirect to the first category if available
  if (categories.length > 0) {
    const firstCategorySlug = categories[0].category.slug;
    redirect(`/games/${slug}/${firstCategorySlug}`);
  }

  // Fallback: show message if no categories
  return (
    <div className="container">
      <div className="page-header">
        <div className="breadcrumb">
          <a href="/">Home</a>
          <span className="breadcrumb-sep">›</span>
          <span>{game.name}</span>
        </div>
        <div className="game-header">
          <div className="game-header-icon">
            {game.icon_url ? (
              <Image
                src={game.icon_url}
                alt={game.name}
                width={56}
                height={56}
              />
            ) : '🎮'}
          </div>
          <div className="game-header-info">
            <h1>{game.name}</h1>
          </div>
        </div>
      </div>
      <div className="empty-state">
        <div className="empty-state-icon">📦</div>
        <p>No categories available for this game yet.</p>
      </div>
    </div>
  );
}

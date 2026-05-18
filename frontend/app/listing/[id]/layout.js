export async function generateMetadata({ params }) {
  const { id } = await params;
  const listingId = String(id || '').trim();
  const title = listingId ? `Listing ${listingId}` : 'Listing';
  const description = 'View this GamesBazaar listing with secure checkout, buyer protection, and seller chat.';

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

export default function ListingLayout({ children }) {
  return children;
}

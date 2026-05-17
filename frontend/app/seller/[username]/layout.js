function sellerNameFromParam(username) {
  return String(username || 'Seller').trim() || 'Seller';
}

export async function generateMetadata({ params }) {
  const { username } = await params;
  const sellerName = sellerNameFromParam(username);
  const title = `${sellerName} Seller Profile`;
  const description = `View ${sellerName}'s seller profile, active listings, reviews, and completed sales on GamesBazaar.`;

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      type: 'profile',
      siteName: 'GamesBazaar',
    },
  };
}

export default function SellerProfileLayout({ children }) {
  return children;
}

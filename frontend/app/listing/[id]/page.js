import { getListingDetail } from '@/lib/api';
import { notFound } from 'next/navigation';

export async function generateMetadata({ params }) {
  const { id } = await params;
  try {
    const listing = await getListingDetail(id);
    return {
      title: `${listing.title} — GamesBazaar`,
      description: listing.description || `${listing.title} for PKR ${listing.price}`,
    };
  } catch {
    return { title: 'Listing Not Found — GamesBazaar' };
  }
}

export default async function ListingDetailPage({ params }) {
  const { id } = await params;
  let listing;

  try {
    listing = await getListingDetail(id);
  } catch {
    notFound();
  }

  return (
    <div className="container">
      <div className="page-header">
        <div className="breadcrumb">
          <a href="/">Home</a>
          <span className="breadcrumb-sep">›</span>
          <span>{listing.game_name}</span>
          <span className="breadcrumb-sep">›</span>
          <span>{listing.category_name}</span>
        </div>
      </div>

      <div className="listing-detail">
        <div className="listing-detail-main">
          <h1 className="listing-detail-title">{listing.title}</h1>

          {/* Filter badges */}
          {listing.filter_display && Object.keys(listing.filter_display).length > 0 && (
            <div className="listing-detail-tags">
              {Object.entries(listing.filter_display).map(([name, value]) => (
                <span key={name} className="listing-tag">
                  {name}: {value}
                </span>
              ))}
            </div>
          )}

          {listing.description && (
            <div className="listing-detail-desc">
              <h3>Description</h3>
              <p>{listing.description}</p>
            </div>
          )}
        </div>

        <div className="listing-detail-sidebar">
          <div className="listing-detail-price-card">
            <div className="listing-detail-price">PKR {listing.price}</div>
            <div className="listing-detail-seller">
              Sold by <strong>{listing.seller_name}</strong>
            </div>
            <div className="listing-detail-date">
              Listed {new Date(listing.created_at).toLocaleDateString()}
            </div>
            <button className="btn btn-primary btn-full" style={{ marginTop: '16px' }}>
              💬 Contact Seller
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

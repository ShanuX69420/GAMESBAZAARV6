'use client';

import { useEffect, useState } from 'react';

// Thumbnail strip + fullscreen viewer for the buyer photos on a review.
// Renders nothing when the review has no photos.
export default function ReviewPhotos({ images }) {
  const [openIndex, setOpenIndex] = useState(-1);
  const count = images ? images.length : 0;

  useEffect(() => {
    if (openIndex < 0) return undefined;
    function handleKey(e) {
      if (e.key === 'Escape') setOpenIndex(-1);
      if (e.key === 'ArrowRight') setOpenIndex((i) => Math.min(i + 1, count - 1));
      if (e.key === 'ArrowLeft') setOpenIndex((i) => Math.max(i - 1, 0));
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [openIndex, count]);

  if (!count) return null;

  return (
    <>
      <div className="review-photos">
        {images.map((image, index) => (
          <button
            key={image.id}
            type="button"
            className="review-photo-thumb"
            onClick={() => setOpenIndex(index)}
            aria-label={`View photo ${index + 1} of ${count}`}
          >
            <img src={image.url} alt="Buyer photo" loading="lazy" />
          </button>
        ))}
      </div>

      {openIndex >= 0 && images[openIndex] && (
        <div className="review-photo-viewer" onClick={() => setOpenIndex(-1)} role="dialog" aria-label="Review photo">
          <button type="button" className="review-photo-viewer-close" aria-label="Close">✕</button>
          {openIndex > 0 && (
            <button
              type="button"
              className="review-photo-viewer-nav review-photo-viewer-prev"
              aria-label="Previous photo"
              onClick={(e) => { e.stopPropagation(); setOpenIndex(openIndex - 1); }}
            >
              ‹
            </button>
          )}
          <img src={images[openIndex].url} alt="Buyer photo" onClick={(e) => e.stopPropagation()} />
          {openIndex < count - 1 && (
            <button
              type="button"
              className="review-photo-viewer-nav review-photo-viewer-next"
              aria-label="Next photo"
              onClick={(e) => { e.stopPropagation(); setOpenIndex(openIndex + 1); }}
            >
              ›
            </button>
          )}
        </div>
      )}
    </>
  );
}

'use client';

// Controlled photo picker for review forms: existing photos (saved on the
// review, removable while editing), new photos awaiting upload, and the
// add-photo button while under the cap. State lives in the parent.
export default function ReviewPhotoPicker({
  existingPhotos = [],
  newPhotos,
  onSelect,
  onRemoveNew,
  onRemoveExisting,
  max,
}) {
  return (
    <div className="review-photos-input">
      <div className="review-photos">
        {existingPhotos.map((photo) => (
          <div key={`existing-${photo.id}`} className="review-photo-thumb">
            <img src={photo.url} alt="Review photo" />
            <button
              type="button"
              className="review-photo-remove"
              onClick={() => onRemoveExisting(photo.id)}
              aria-label="Remove photo"
            >
              ✕
            </button>
          </div>
        ))}
        {newPhotos.map((photo, index) => (
          <div key={photo.previewUrl} className="review-photo-thumb">
            <img src={photo.previewUrl} alt="Photo to upload" />
            <button
              type="button"
              className="review-photo-remove"
              onClick={() => onRemoveNew(index)}
              aria-label="Remove photo"
            >
              ✕
            </button>
          </div>
        ))}
        {existingPhotos.length + newPhotos.length < max && (
          <label className="review-photo-add">
            <input type="file" accept="image/*" multiple onChange={onSelect} hidden />
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/>
              <circle cx="12" cy="13" r="4"/>
            </svg>
            <span>Add photo</span>
          </label>
        )}
      </div>
      <span className="review-photos-hint">
        Optional — attach up to {max} photos of what you received
      </span>
    </div>
  );
}

// The check mark next to an in-house shop's name. Only sellers flagged
// is_official_store in the admin get one — a badge everybody carries stops
// telling buyers anything.
//
// Fill is --green-solid (identical in both themes, made to sit under white)
// so the knocked-out check stays legible in light and dark.

export default function OfficialStoreBadge({ showLabel = false, className = '' }) {
  const classes = [
    'official-store-badge',
    showLabel ? 'official-store-badge-pill' : '',
    className,
  ].filter(Boolean).join(' ');

  return (
    <span className={classes} title="Official Store" role="img" aria-label="Official Store">
      <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <circle cx="12" cy="12" r="10" fill="var(--green-solid)" />
        <path
          d="M7.6 12.4l3 3 5.8-6"
          fill="none"
          stroke="#FFFFFF"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {showLabel && <span className="official-store-badge-text">Official Store</span>}
    </span>
  );
}

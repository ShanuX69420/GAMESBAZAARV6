import { ImageResponse } from 'next/og';

export const alt = 'GamesBazaar digital gaming marketplace';
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = 'image/png';

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          alignItems: 'center',
          background: '#FFFFFF',
          color: '#111827',
          display: 'flex',
          flexDirection: 'column',
          fontFamily: 'Arial, sans-serif',
          height: '100%',
          justifyContent: 'center',
          padding: '72px',
          width: '100%',
        }}
      >
        <div
          style={{
            alignItems: 'center',
            display: 'flex',
            gap: 20,
            marginBottom: 28,
          }}
        >
          <svg width="72" height="72" viewBox="0 0 100 100">
            <polygon points="50,4 89.84,27 89.84,73 50,96 10.16,73 10.16,27" fill="#18874A" />
            <rect x="25" y="38" width="50" height="24" rx="12" fill="#FFFFFF" />
            <rect x="35.5" y="43.5" width="5.5" height="13" rx="1.8" fill="#18874A" />
            <rect x="31.75" y="47.25" width="13" height="5.5" rx="1.8" fill="#18874A" />
            <circle cx="60" cy="46.5" r="3.4" fill="#18874A" />
            <circle cx="66.5" cy="53" r="3.4" fill="#18874A" />
          </svg>
          <div
            style={{
              color: '#18874A',
              fontSize: 42,
              fontWeight: 700,
              letterSpacing: 0,
            }}
          >
            GamesBazaar
          </div>
        </div>
        <div
          style={{
            fontSize: 78,
            fontWeight: 800,
            letterSpacing: 0,
            lineHeight: 1.05,
            maxWidth: 940,
            textAlign: 'center',
          }}
        >
          Pakistan's Digital Gaming Marketplace
        </div>
        <div
          style={{
            color: '#596066',
            fontSize: 32,
            lineHeight: 1.35,
            marginTop: 32,
            maxWidth: 880,
            textAlign: 'center',
          }}
        >
          Buy and sell game accounts, top-ups, items, and boosting services with secure checkout.
        </div>
      </div>
    ),
    size,
  );
}

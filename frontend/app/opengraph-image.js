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
          background: '#08111f',
          color: '#f8fafc',
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
            color: '#22c55e',
            fontSize: 42,
            fontWeight: 700,
            letterSpacing: 0,
            marginBottom: 28,
          }}
        >
          GamesBazaar
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
            color: '#cbd5e1',
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

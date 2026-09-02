/** @type {import('next').NextConfig} */
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { retiredRedirects } from './lib/retiredRoutes.mjs';

const projectRoot = dirname(fileURLToPath(import.meta.url));
const isProduction = process.env.NODE_ENV === 'production';
const allowLocalProductionBuild = ['1', 'true', 'yes', 'on'].includes(
  String(process.env.LOCAL_PRODUCTION_BUILD || '').trim().toLowerCase()
);
const manifestCacheControl = 'public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800';
const iconCacheControl = 'public, max-age=2592000, stale-while-revalidate=604800';

function imageRemotePatternFromUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(value.includes('://') ? value : `https://${value}`);
    if (!['http:', 'https:'].includes(url.protocol)) return null;
    const pattern = {
      protocol: url.protocol.slice(0, -1),
      hostname: url.hostname,
    };
    if (url.port) pattern.port = url.port;
    return pattern;
  } catch {
    return null;
  }
}

const configuredImagePatterns = [
  process.env.NEXT_PUBLIC_API_URL,
  process.env.NEXT_PUBLIC_SITE_URL,
  ...(process.env.NEXT_PUBLIC_IMAGE_HOSTS || '').split(','),
]
  .map((value) => imageRemotePatternFromUrl(String(value || '').trim()))
  .filter(Boolean);

const devImagePatterns = isProduction ? [] : [
  { protocol: 'http', hostname: 'localhost' },
  { protocol: 'http', hostname: '127.0.0.1' },
];

const imageRemotePatterns = [
  ...configuredImagePatterns,
  ...devImagePatterns,
].filter((pattern, index, patterns) => (
  index === patterns.findIndex((candidate) => (
    candidate.protocol === pattern.protocol &&
    candidate.hostname === pattern.hostname &&
    (candidate.port || '') === (pattern.port || '')
  ))
));

const nextConfig = {
  poweredByHeader: false,
  turbopack: {
    root: projectRoot,
  },
  async redirects() {
    return [
      // The Offline Activation section was retired 2026-08-23; the page was
      // indexed and in the sitemap, so send old visitors somewhere useful.
      {
        source: '/offline-activation',
        destination: '/keys',
        permanent: true,
      },
      // Direct game top-ups were retired 2026-09-02; the section page now
      // hosts the PS Plus / Game Pass codes that lived under it.
      {
        source: '/top-ups',
        destination: '/subscriptions',
        permanent: true,
      },
      // Per-page fallout of the same retirements (deleted game+category
      // pages, emptied game pages, the offline-activation category on every
      // game) — data lives in lib/retiredRoutes.mjs.
      ...retiredRedirects(),
    ];
  },
  images: {
    formats: ['image/webp'],
    remotePatterns: imageRemotePatterns,
    dangerouslyAllowLocalIP: !isProduction || allowLocalProductionBuild,
  },
  async headers() {
    return [
      {
        source: '/manifest.json',
        headers: [
          { key: 'Cache-Control', value: manifestCacheControl },
        ],
      },
      {
        source: '/icons/:path*',
        headers: [
          { key: 'Cache-Control', value: iconCacheControl },
        ],
      },
      {
        source: '/apple-touch-icon.png',
        headers: [
          { key: 'Cache-Control', value: iconCacheControl },
        ],
      },
      {
        source: '/favicon.ico',
        headers: [
          { key: 'Cache-Control', value: iconCacheControl },
        ],
      },
    ];
  },
};

export default nextConfig;

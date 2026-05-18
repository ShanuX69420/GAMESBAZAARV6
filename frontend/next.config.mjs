/** @type {import('next').NextConfig} */
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = dirname(fileURLToPath(import.meta.url));
const isProduction = process.env.NODE_ENV === 'production';

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
  turbopack: {
    root: projectRoot,
  },
  images: {
    formats: ['image/webp'],
    remotePatterns: imageRemotePatterns,
  },
};

export default nextConfig;

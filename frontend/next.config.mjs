/** @type {import('next').NextConfig} */
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = dirname(fileURLToPath(import.meta.url));
const isProduction = process.env.NODE_ENV === 'production';

function originFromEnv(value) {
  if (!value) return null;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

function websocketOriginFromApi(value) {
  if (!value) return null;
  try {
    const url = new URL(value);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return url.origin;
  } catch {
    return null;
  }
}

const apiOrigin = originFromEnv(process.env.NEXT_PUBLIC_API_URL);
const wsOrigin = originFromEnv(process.env.NEXT_PUBLIC_WS_URL)
  || websocketOriginFromApi(process.env.NEXT_PUBLIC_API_URL);
const connectSrc = ["'self'", apiOrigin, wsOrigin].filter(Boolean).join(' ');
const securityHeaders = [
  {
    key: 'Content-Security-Policy',
    value: [
      "default-src 'self'",
      "base-uri 'self'",
      "frame-ancestors 'none'",
      "object-src 'none'",
      "form-action 'self'",
      "img-src 'self' data: blob: http: https:",
      "style-src 'self' 'unsafe-inline'",
      "script-src 'self' 'unsafe-inline'",
      `connect-src ${connectSrc}`,
    ].join('; '),
  },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' },
];

const nextConfig = {
  turbopack: {
    root: projectRoot,
  },
  async headers() {
    if (!isProduction) return [];
    return [
      {
        source: '/:path*',
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;

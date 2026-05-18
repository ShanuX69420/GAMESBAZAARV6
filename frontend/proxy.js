import { NextResponse } from 'next/server';

const GOOGLE_IDENTITY_PARENT_SRC = 'https://accounts.google.com/gsi/';
const GOOGLE_IDENTITY_SCRIPT_SRC = 'https://accounts.google.com/gsi/client';
const GOOGLE_IDENTITY_STYLE_SRC = 'https://accounts.google.com/gsi/style';
const STATIC_CSP_PATHS = new Set(['/privacy-policy', '/terms-of-service']);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function originFromEnv(value, allowedProtocols = ['http:', 'https:', 'ws:', 'wss:']) {
  if (!value) return null;
  try {
    const url = new URL(value.includes('://') ? value : `https://${value}`);
    if (!allowedProtocols.includes(url.protocol)) return null;
    return url.origin;
  } catch {
    return null;
  }
}

function originsFromEnvList(value, allowedProtocols = ['http:', 'https:']) {
  return [
    ...new Set(
      String(value || '')
        .split(',')
        .map((item) => originFromEnv(item.trim(), allowedProtocols))
        .filter(Boolean),
    ),
  ];
}

function pathnameFromRequest(request) {
  const pathname = request.nextUrl?.pathname || (request.url ? new URL(request.url).pathname : '');
  return pathname.replace(/\/+$/, '') || '/';
}

function envFlag(value) {
  return ['1', 'true', 'yes', 'on'].includes(String(value || '').trim().toLowerCase());
}

function buildCspHeader(nonce) {
  const apiOrigin = originFromEnv(process.env.NEXT_PUBLIC_API_URL, ['https:']);
  const wsOrigin = originFromEnv(process.env.NEXT_PUBLIC_WS_URL, ['wss:']);
  const imageOrigins = originsFromEnvList(process.env.NEXT_PUBLIC_IMAGE_HOSTS, ['http:', 'https:']);

  const connectSrc = ["'self'", apiOrigin, wsOrigin, GOOGLE_IDENTITY_PARENT_SRC].filter(Boolean).join(' ');
  const imgSrc = ["'self'", 'data:', 'blob:', apiOrigin, ...imageOrigins].filter(Boolean).join(' ');
  const scriptSrc = nonce
    ? ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'", GOOGLE_IDENTITY_SCRIPT_SRC]
    : ["'self'", "'unsafe-inline'", GOOGLE_IDENTITY_SCRIPT_SRC];
  const styleSrc = nonce
    ? ["'self'", `'nonce-${nonce}'`, 'https://fonts.googleapis.com', GOOGLE_IDENTITY_STYLE_SRC]
    : ["'self'", "'unsafe-inline'", 'https://fonts.googleapis.com', GOOGLE_IDENTITY_STYLE_SRC];

  return [
    "default-src 'self'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "form-action 'self'",
    `font-src 'self' https://fonts.gstatic.com`,
    `img-src ${imgSrc}`,
    `style-src ${styleSrc.join(' ')}`,
    "style-src-attr 'unsafe-inline'",
    `script-src ${scriptSrc.join(' ')}`,
    "script-src-attr 'none'",
    `connect-src ${connectSrc}`,
    `frame-src ${GOOGLE_IDENTITY_PARENT_SRC}`,
    'upgrade-insecure-requests',
  ].join('; ');
}

function createNonce() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

// ---------------------------------------------------------------------------
// Proxy
// ---------------------------------------------------------------------------

export function proxy(request) {
  if (process.env.NODE_ENV !== 'production') {
    return NextResponse.next();
  }

  const useStaticCsp = STATIC_CSP_PATHS.has(pathnameFromRequest(request));
  const nonce = useStaticCsp ? null : createNonce();
  const cspHeader = buildCspHeader(nonce);

  const requestHeaders = new Headers(request.headers);
  if (nonce) {
    requestHeaders.set('x-nonce', nonce);
  }
  requestHeaders.set('Content-Security-Policy', cspHeader);

  const response = NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });

  response.headers.set('Content-Security-Policy', cspHeader);
  const hstsValue = 'max-age=63072000; includeSubDomains' + (envFlag(process.env.SECURE_HSTS_PRELOAD) ? '; preload' : '');
  response.headers.set('Strict-Transport-Security', hstsValue);
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('X-Frame-Options', 'DENY');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  response.headers.set('X-DNS-Prefetch-Control', 'on');
  response.headers.set('X-Permitted-Cross-Domain-Policies', 'none');
  response.headers.set(
    'Permissions-Policy',
    'camera=(), microphone=(), geolocation=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()',
  );

  return response;
}

export const config = {
  matcher: [
    {
      source: '/((?!api|_next/static|_next/image|favicon.ico|logo.png|apple-touch-icon.png|manifest.json|robots.txt|sitemap.xml).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
};

import { NextResponse } from 'next/server';

const GOOGLE_IDENTITY_ORIGIN = 'https://accounts.google.com';
const GOOGLE_IDENTITY_SCRIPT_SRC = 'https://accounts.google.com/gsi/client';
const GOOGLE_IDENTITY_STYLE_SRC = 'https://accounts.google.com/gsi/style';
const GOOGLE_TAG_MANAGER_ORIGIN = 'https://www.googletagmanager.com';
const GOOGLE_ANALYTICS_ORIGINS = [
  'https://www.google-analytics.com',
  'https://ssl.google-analytics.com',
  'https://analytics.google.com',
  'https://region1.google-analytics.com',
  'https://stats.g.doubleclick.net',
];
const GOOGLE_ADS_ORIGINS = [
  'https://pagead2.googlesyndication.com',
  'https://www.googleadservices.com',
  'https://googleads.g.doubleclick.net',
  'https://adservice.google.com',
  'https://tpc.googlesyndication.com',
  'https://td.doubleclick.net',
  'https://www.google.com',
  'https://www.google.com.pk',
];
const META_ORIGINS = [
  'https://connect.facebook.net',
  'https://www.facebook.com',
  'https://web.facebook.com',
  'https://graph.facebook.com',
  'https://static.xx.fbcdn.net',
];
const META_IMAGE_ORIGINS = [
  ...META_ORIGINS,
  'https://*.fbcdn.net',
];

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

function envFlag(value) {
  return ['1', 'true', 'yes', 'on'].includes(String(value || '').trim().toLowerCase());
}

function sourceList(values) {
  return [...new Set(values.filter(Boolean))].join(' ');
}

function buildCspHeader() {
  const apiOrigin = originFromEnv(process.env.NEXT_PUBLIC_API_URL, ['https:']);
  const wsOrigin = originFromEnv(process.env.NEXT_PUBLIC_WS_URL, ['wss:']);
  const imageOrigins = originsFromEnvList(process.env.NEXT_PUBLIC_IMAGE_HOSTS, ['http:', 'https:']);

  const analyticsAndAdsOrigins = [
    GOOGLE_TAG_MANAGER_ORIGIN,
    ...GOOGLE_ANALYTICS_ORIGINS,
    ...GOOGLE_ADS_ORIGINS,
  ];
  const scriptSrc = sourceList([
    "'self'",
    "'unsafe-inline'",
    GOOGLE_IDENTITY_SCRIPT_SRC,
    GOOGLE_TAG_MANAGER_ORIGIN,
    ...GOOGLE_ANALYTICS_ORIGINS,
    ...GOOGLE_ADS_ORIGINS,
    'https://connect.facebook.net',
  ]);
  const styleSrc = sourceList([
    "'self'",
    "'unsafe-inline'",
    'https://fonts.googleapis.com',
    GOOGLE_IDENTITY_STYLE_SRC,
  ]);
  const connectSrc = sourceList([
    "'self'",
    apiOrigin,
    wsOrigin,
    GOOGLE_IDENTITY_ORIGIN,
    ...analyticsAndAdsOrigins,
    ...META_ORIGINS,
  ]);
  const imgSrc = sourceList([
    "'self'",
    'data:',
    'blob:',
    apiOrigin,
    ...imageOrigins,
    'https://www.gstatic.com',
    'https://ssl.gstatic.com',
    'https://lh3.googleusercontent.com',
    ...analyticsAndAdsOrigins,
    ...META_IMAGE_ORIGINS,
  ]);
  const frameSrc = sourceList([
    GOOGLE_IDENTITY_ORIGIN,
    GOOGLE_TAG_MANAGER_ORIGIN,
    ...GOOGLE_ADS_ORIGINS,
    'https://www.facebook.com',
    'https://web.facebook.com',
  ]);

  return [
    "default-src 'self'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "form-action 'self'",
    "font-src 'self' data: https://fonts.gstatic.com",
    `img-src ${imgSrc}`,
    `style-src ${styleSrc}`,
    "style-src-attr 'unsafe-inline'",
    `script-src ${scriptSrc}`,
    "script-src-attr 'none'",
    `connect-src ${connectSrc}`,
    `frame-src ${frameSrc}`,
    "worker-src 'self' blob:",
    "manifest-src 'self'",
    'upgrade-insecure-requests',
  ].join('; ');
}

// ---------------------------------------------------------------------------
// Proxy
// ---------------------------------------------------------------------------

export function proxy(request) {
  if (process.env.NODE_ENV !== 'production' || envFlag(process.env.LOCAL_PRODUCTION_BUILD)) {
    return NextResponse.next();
  }

  const response = NextResponse.next();

  response.headers.set('Content-Security-Policy', buildCspHeader());
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

import { NextResponse } from 'next/server';

function originFromEnv(value) {
  if (!value) return null;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

function buildCspHeader(nonce) {
  const apiOrigin = originFromEnv(process.env.NEXT_PUBLIC_API_URL);
  const wsOrigin = originFromEnv(process.env.NEXT_PUBLIC_WS_URL);
  const connectSrc = ["'self'", apiOrigin, wsOrigin].filter(Boolean).join(' ');
  const imgSrc = ["'self'", 'data:', 'blob:', apiOrigin].filter(Boolean).join(' ');

  return [
    "default-src 'self'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "form-action 'self'",
    "font-src 'self'",
    `img-src ${imgSrc}`,
    `style-src 'self' 'nonce-${nonce}'`,
    "style-src-attr 'unsafe-inline'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    `connect-src ${connectSrc}`,
    'upgrade-insecure-requests',
  ].join('; ');
}

export function proxy(request) {
  if (process.env.NODE_ENV !== 'production') {
    return NextResponse.next();
  }

  const nonce = Buffer.from(crypto.randomUUID()).toString('base64');
  const cspHeader = buildCspHeader(nonce);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set('Content-Security-Policy', cspHeader);

  const response = NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });
  response.headers.set('Content-Security-Policy', cspHeader);
  return response;
}

export const config = {
  matcher: [
    {
      source: '/((?!api|_next/static|_next/image|favicon.ico).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
};

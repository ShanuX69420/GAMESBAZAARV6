const isProduction = process.env.NODE_ENV === 'production';

function requireProductionUrl(name, value, allowedProtocols) {
  if (!isProduction) return;
  if (!value) {
    throw new Error(`${name} must be set for production builds.`);
  }

  const url = new URL(value);
  if (!allowedProtocols.includes(url.protocol)) {
    throw new Error(`${name} must use ${allowedProtocols.join(' or ')} in production.`);
  }
  if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') {
    throw new Error(`${name} cannot point to localhost in production.`);
  }
}

requireProductionUrl('NEXT_PUBLIC_API_URL', process.env.NEXT_PUBLIC_API_URL, ['https:']);
requireProductionUrl('NEXT_PUBLIC_WS_URL', process.env.NEXT_PUBLIC_WS_URL, ['wss:']);

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function websocketBaseFromApiBase() {
  try {
    const url = new URL(API_BASE);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return url.origin;
  } catch {
    return 'ws://localhost:8000';
  }
}

export const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || websocketBaseFromApiBase();

export const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || '';

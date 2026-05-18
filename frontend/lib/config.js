const isProduction = process.env.NODE_ENV === 'production';
const isServerRuntime = typeof window === 'undefined';
const allowLocalProductionBuild = envFlag(process.env.LOCAL_PRODUCTION_BUILD);

function envFlag(value) {
  return ['1', 'true', 'yes', 'on'].includes(String(value || '').trim().toLowerCase());
}

function isLocalHostname(hostname) {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';
}

function requireProductionUrl(name, value, allowedProtocols, localProtocols = allowedProtocols) {
  if (!isProduction || !isServerRuntime) return;
  if (allowLocalProductionBuild && !value) return;

  if (!value) {
    throw new Error(`${name} must be set for production builds.`);
  }

  const url = new URL(value);
  const isLocalUrl = isLocalHostname(url.hostname);
  const protocols = allowLocalProductionBuild && isLocalUrl ? localProtocols : allowedProtocols;

  if (!protocols.includes(url.protocol)) {
    throw new Error(`${name} must use ${allowedProtocols.join(' or ')} in production.`);
  }
  if (isLocalUrl && !allowLocalProductionBuild) {
    throw new Error(`${name} cannot point to localhost in production.`);
  }
}

requireProductionUrl('NEXT_PUBLIC_API_URL', process.env.NEXT_PUBLIC_API_URL, ['https:'], ['http:', 'https:']);
requireProductionUrl('NEXT_PUBLIC_WS_URL', process.env.NEXT_PUBLIC_WS_URL, ['wss:'], ['ws:', 'wss:']);

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

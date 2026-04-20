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

import { API_BASE } from '@/lib/config';

// DRF's throttle message is "Request was throttled. Expected available in
// 3226 seconds." — true, and useless to the person reading it.
function rephraseThrottleMessage(detail) {
  const seconds = Number(String(detail).match(/(\d+)\s*seconds?/)?.[1]);
  if (!Number.isFinite(seconds)) {
    return 'Too many attempts from your network. Please try again later.';
  }
  const minutes = Math.ceil(seconds / 60);
  const hours = Math.ceil(minutes / 60);
  const wait = minutes < 60
    ? `${minutes} minute${minutes === 1 ? '' : 's'}`
    : `${hours} hour${hours === 1 ? '' : 's'}`;
  return `Too many attempts from your network. Please try again in about ${wait}.`;
}

/**
 * Turn a DRF error body into one readable sentence.
 *
 * Serializer errors arrive as {field: [msg, ...]}. Showing only the first
 * message makes people rediscover the remaining rules one rejected submit at
 * a time — which is how signups burned through their whole rate limit.
 */
export function formatApiError(data, fallback) {
  if (!data || typeof data !== 'object') return fallback;
  if (typeof data.detail === 'string' && /throttled/i.test(data.detail)) {
    return rephraseThrottleMessage(data.detail);
  }
  const messages = Object.values(data)
    .flat()
    .filter((message) => typeof message === 'string');
  return messages.length ? messages.join(' ') : fallback;
}

export async function requestLogout() {
  try {
    const res = await fetch(`${API_BASE}/api/auth/logout/`, {
      method: 'POST',
      credentials: 'include',
    });
    if (!res.ok && process.env.NODE_ENV !== 'production') {
      console.warn(`Logout request failed with status ${res.status}`);
    }
  } catch {
    // If the API is offline, local auth state should still be cleared.
  }
}

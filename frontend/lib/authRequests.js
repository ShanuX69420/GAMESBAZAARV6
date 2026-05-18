import { API_BASE } from '@/lib/config';

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

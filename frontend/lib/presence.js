'use client';

// Live seller presence for the online/offline dot.
//
// Catalog payloads carry seller_last_active, but they travel through caches
// that all outlive the 120s online window (Django's 30s browse cache, nginx's
// 300s shared cache, Next.js' 120s revalidate). A seller whose tab heartbeats
// every 65s therefore reads as offline until the cache turns over, and a page
// that never re-fetches keeps that wrong dot forever. Chat avoids this because
// the socket pushes presence; every other page gets it from here instead.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { getPresence, isOnlineFromLastActive } from '@/lib/api';

export const PRESENCE_POLL_MS = 30000;

// The live answer wins, but never let a cached payload's newer timestamp be
// thrown away by an older one (page loaded, then a poll raced past it).
export function pickLastActive(liveIso, fallbackIso) {
  if (!liveIso) return fallbackIso || null;
  if (!fallbackIso) return liveIso;
  return new Date(liveIso).getTime() >= new Date(fallbackIso).getTime() ? liveIso : fallbackIso;
}

export function useLivePresence(userIds) {
  const idKey = useMemo(() => {
    const ids = [...new Set((userIds || []).filter((id) => id !== null && id !== undefined))];
    ids.sort((a, b) => Number(a) - Number(b));
    return ids.join(',');
  }, [userIds]);

  const [presence, setPresence] = useState({});
  const [presenceNow, setPresenceNow] = useState(() => Date.now());

  useEffect(() => {
    if (!idKey) return undefined;
    const ids = idKey.split(',');
    let cancelled = false;
    let inFlight = false;
    let controller = null;

    const load = async () => {
      if (document.visibilityState !== 'visible') return;
      if (inFlight) return;
      inFlight = true;
      controller = new AbortController();
      try {
        const users = await getPresence(ids, { signal: controller.signal });
        if (cancelled) return;
        setPresence((prev) => ({ ...prev, ...users }));
        setPresenceNow(Date.now());
      } catch {
        // Keep the last known presence — the next tick retries.
      } finally {
        inFlight = false;
        controller = null;
      }
    };

    const tick = () => {
      setPresenceNow(Date.now());
      load();
    };

    const handleWake = () => {
      if (document.visibilityState === 'visible') tick();
    };

    load();
    const interval = setInterval(tick, PRESENCE_POLL_MS);
    document.addEventListener('visibilitychange', handleWake);
    window.addEventListener('focus', handleWake);

    return () => {
      cancelled = true;
      if (controller) controller.abort();
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleWake);
      window.removeEventListener('focus', handleWake);
    };
  }, [idKey]);

  const lastActiveFor = useCallback(
    (userId, fallbackIso = null) => pickLastActive(presence[String(userId)], fallbackIso),
    [presence],
  );

  const isOnline = useCallback(
    (userId, fallbackIso = null) => isOnlineFromLastActive(
      lastActiveFor(userId, fallbackIso),
      presenceNow,
    ),
    [lastActiveFor, presenceNow],
  );

  return { presenceNow, lastActiveFor, isOnline };
}

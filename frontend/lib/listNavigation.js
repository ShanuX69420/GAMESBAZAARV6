'use client';

import { startTransition, useCallback } from 'react';
import { useRouter } from 'next/navigation';

// Client-side navigation for long lists of plain <a> rows.
//
// A list page like /keys or /games renders 400–560 rows. As next/link each
// row was a component with its own hooks, and hydrating all of them was one
// ~90 ms main-thread task (4x CPU throttle; about double on a budget phone)
// during which a tap could not be answered — one of the sources behind the
// Search Console "INP > 200 ms (mobile)" issue (2026-09-13). With prefetch
// off, the only thing next/link did for these rows was turn a click into a
// router navigation, which one handler on the grid can do for every row.
// The rows stay ordinary anchors, so crawlers, middle-click, ctrl-click and
// open-in-new-tab behave exactly as before.
export function useListClickNavigation() {
  const router = useRouter();
  return useCallback((event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = event.target.closest ? event.target.closest('a[href]') : null;
    if (!anchor || !event.currentTarget.contains(anchor)) return;
    if (anchor.target && anchor.target !== '_self') return;
    if (anchor.hasAttribute('download')) return;
    const href = anchor.getAttribute('href');
    // Same-site paths only; anything else keeps the browser's default.
    if (!href || !href.startsWith('/') || href.startsWith('//')) return;
    event.preventDefault();
    startTransition(() => {
      router.push(href);
    });
  }, [router]);
}

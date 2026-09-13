'use client';

import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import Script from 'next/script';
import { captureFirstTouch } from '@/lib/attribution';
import { runWhenIdle } from '@/lib/idle';

const GA_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID;
const PIXEL_ID = process.env.NEXT_PUBLIC_META_PIXEL_ID;

// Queueing stubs are installed at module-evaluation time — before React
// mounts anything — so events fired from mount effects (e.g. view_item on a
// listing page) are queued and replayed once the real scripts load, instead
// of being dropped. This is the same queue both libraries' official snippets
// create; gtag.js and fbevents.js drain it on arrival.
function installStubs() {
  if (typeof window === 'undefined') return;

  if (GA_ID && !window.__gaInitialized) {
    window.__gaInitialized = true;
    window.dataLayer = window.dataLayer || [];
    // gtag.js requires `arguments` objects on the dataLayer, not arrays.
    window.gtag = window.gtag || function gtag() { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', GA_ID);
  }

  if (PIXEL_ID && !window.fbq) {
    const fbq = function () {
      fbq.callMethod ? fbq.callMethod.apply(fbq, arguments) : fbq.queue.push(arguments);
    };
    fbq.push = fbq;
    fbq.loaded = true;
    fbq.version = '2.0';
    fbq.queue = [];
    window.fbq = fbq;
    if (!window._fbq) window._fbq = fbq;
    // No automatic configuration: with it on, fbevents.js pulls a ~500 KB
    // config script that opts the pixel into inferred button-click events,
    // form-field scraping and microdata scanning — measured at 60–100 ms of
    // main-thread work on EVERY tap on a phone (the last big mobile INP cost
    // after the 2026-09-13 fixes; Shayan chose to drop it). Explicit events,
    // the manual match key below and the server-side Conversions API are
    // unaffected. Must be set before init.
    window.fbq('set', 'autoConfig', false, PIXEL_ID);
    // Advanced matching: PKR-only Pakistani marketplace, so country is a
    // constant match key. fbevents.js hashes it before sending.
    window.fbq('init', PIXEL_ID, { country: 'pk' });
    window.fbq('track', 'PageView');
    runWhenIdle(() => {
      const script = document.createElement('script');
      script.async = true;
      script.src = 'https://connect.facebook.net/en_US/fbevents.js';
      document.head.appendChild(script);
    });
  }
}

// Third-party tag scripts run only once the page has loaded AND the browser
// is idle (lib/idle.js). Evaluating gtag.js + fbevents.js (+ the pixel's
// config script) is ~550 ms of main-thread time on a 4x-throttled phone, and
// it used to land 1-3 s after load - exactly when visitors start tapping, so
// a tap could wait behind it (Search Console mobile INP > 200 ms,
// 2026-09-13). Nothing is lost by waiting: every gtag()/fbq() call queues in
// the stubs above and is replayed when the real script arrives.
installStubs();
// Same module-eval timing: document.referrer still holds the external
// referrer here; by the first route change it would be meaningless.
captureFirstTouch();

// Meta Pixel only counts the initial page load by itself; client-side route
// changes must be reported manually. GA4 needs no equivalent — its Enhanced
// Measurement ("page changes based on browser history events") covers them.
function MetaPixelRouteTracker() {
  const pathname = usePathname();
  const initialLoad = useRef(true);

  useEffect(() => {
    if (initialLoad.current) {
      // installStubs() already sent the first PageView.
      initialLoad.current = false;
      return;
    }
    if (typeof window.fbq === 'function') {
      window.fbq('track', 'PageView');
    }
  }, [pathname]);

  return null;
}

export default function Analytics() {
  return (
    <>
      {/* lazyOnload = injected during browser idle time after load, for the
          same reason fbevents.js waits above. */}
      {GA_ID && (
        <Script
          src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`}
          strategy="lazyOnload"
        />
      )}
      {PIXEL_ID && (
        <>
          <noscript>
            <img
              height="1"
              width="1"
              style={{ display: 'none' }}
              src={`https://www.facebook.com/tr?id=${PIXEL_ID}&ev=PageView&noscript=1`}
              alt=""
            />
          </noscript>
          <MetaPixelRouteTracker />
        </>
      )}
    </>
  );
}

'use client';

import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import Script from 'next/script';

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
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://connect.facebook.net/en_US/fbevents.js';
    document.head.appendChild(script);
    window.fbq('init', PIXEL_ID);
    window.fbq('track', 'PageView');
  }
}
installStubs();

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
      {GA_ID && (
        <Script
          src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`}
          strategy="afterInteractive"
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

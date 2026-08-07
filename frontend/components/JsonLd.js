import { Fragment, createElement } from 'react';

function safeJsonLd(data) {
  return JSON.stringify(data).replace(/</g, '\\u003c');
}

export default function JsonLd({ data }) {
  if (!data) return null;

  // One <script> per object, never a single top-level JSON array. Arrays are
  // legal JSON-LD and Google reads them fine, but third-party scripts on the
  // page (pixels, in-app-browser injections) parse the block and go straight
  // for data['@context'] — undefined on an array, so they throw and give up
  // on our markup. That filled Sentry with TypeErrors from every page type.
  if (Array.isArray(data)) {
    return createElement(
      Fragment,
      null,
      ...data.filter(Boolean).map((item, index) => createElement('script', {
        key: index,
        type: 'application/ld+json',
        dangerouslySetInnerHTML: { __html: safeJsonLd(item) },
      })),
    );
  }

  return createElement('script', {
    type: 'application/ld+json',
    dangerouslySetInnerHTML: { __html: safeJsonLd(data) },
  });
}

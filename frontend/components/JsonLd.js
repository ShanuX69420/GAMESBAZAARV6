import { createElement } from 'react';

function safeJsonLd(data) {
  return JSON.stringify(data).replace(/</g, '\\u003c');
}

export default function JsonLd({ data }) {
  if (!data) return null;

  return createElement('script', {
    type: 'application/ld+json',
    dangerouslySetInnerHTML: { __html: safeJsonLd(data) },
  });
}

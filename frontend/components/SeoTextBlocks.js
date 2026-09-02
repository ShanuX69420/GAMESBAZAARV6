import { Fragment } from 'react';
import Link from 'next/link';
import { parseInlineLinks } from '@/lib/seoText';

// One run of copy with its [text](/path) links rendered as real links.
export function SeoInline({ text }) {
  const parts = parseInlineLinks(text);
  if (typeof parts === 'string') return parts;
  return parts.map((part, index) => (
    part.href
      ? <Link key={index} href={part.href}>{part.text}</Link>
      : <Fragment key={index}>{part.text}</Fragment>
  ));
}

// Server-rendered so crawlers see the text without JS. Takes the blocks from
// splitSeoBlocks: "## " blocks become subheadings, "### " sub-subheadings
// (FAQ questions), everything else a paragraph.
export default function SeoTextBlocks({ blocks }) {
  return blocks.map((block, index) => {
    if (block.startsWith('### ')) {
      return <h3 key={index}><SeoInline text={block.slice(4).trim()} /></h3>;
    }
    if (block.startsWith('## ')) {
      return <h2 key={index}><SeoInline text={block.slice(3).trim()} /></h2>;
    }
    return <p key={index}><SeoInline text={block} /></p>;
  });
}

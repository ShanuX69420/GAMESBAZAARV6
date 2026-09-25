import { Fragment } from 'react';
import Link from 'next/link';
import { parseInlineLinks, parseSeoTable } from '@/lib/seoText';

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

// A "| a | b |" block (the live price list). Wrapped so a wide table scrolls
// inside itself on a phone instead of widening the page.
function SeoTable({ table }) {
  return (
    <div className="seo-table-wrap">
      <table>
        <thead>
          <tr>
            {table.head.map((cell, index) => (
              <th key={index} scope="col"><SeoInline text={cell} /></th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, index) => <td key={index}><SeoInline text={cell} /></td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Server-rendered so crawlers see the text without JS. Takes the blocks from
// splitSeoBlocks: "## " blocks become subheadings, "### " sub-subheadings
// (FAQ questions), "| a | b |" blocks tables, everything else a paragraph.
export default function SeoTextBlocks({ blocks }) {
  return blocks.map((block, index) => {
    const table = parseSeoTable(block);
    if (table) return <SeoTable key={index} table={table} />;
    if (block.startsWith('### ')) {
      return <h3 key={index}><SeoInline text={block.slice(4).trim()} /></h3>;
    }
    if (block.startsWith('## ')) {
      return <h2 key={index}><SeoInline text={block.slice(3).trim()} /></h2>;
    }
    return <p key={index}><SeoInline text={block} /></p>;
  });
}

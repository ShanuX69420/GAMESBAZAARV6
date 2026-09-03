import JsonLd from '@/components/JsonLd';
import SeoTextBlocks from '@/components/SeoTextBlocks';
import { faqPageJsonLd } from '@/lib/seo';
import { extractSeoFaq, splitSeoBlocks } from '@/lib/seoText';

// Server-rendered so crawlers see the text without JS. Copy conventions
// (paragraphs, "## " headings, [text](/path) links) live in lib/seoText.js.
// The FAQPage JSON-LD is built from the same blocks the section renders
// ("### " question + the paragraph under it), so the markup can never claim
// a question or answer the visible page doesn't show. Shared by the
// game+category page and its region pages.
export default function CategorySeoText({ text }) {
  const blocks = splitSeoBlocks(text);
  if (!blocks.length) return null;
  const faq = extractSeoFaq(blocks);

  return (
    <div className="container">
      {faq.length > 0 && <JsonLd data={faqPageJsonLd([{ questions: faq }])} />}
      <section className="category-seo-text">
        <SeoTextBlocks blocks={blocks} />
      </section>
    </div>
  );
}

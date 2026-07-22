import { splitUrls } from '@/lib/linkify';

// Renders user-written text with bare URLs turned into clickable links.
// The text is never parsed as HTML — everything besides URLs stays plain.
export default function Linkified({ text }) {
  const parts = splitUrls(text);
  if (!Array.isArray(parts)) return parts;
  return parts.map((part, i) =>
    part.href ? (
      <a
        key={i}
        href={part.href}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="linkified-url"
      >
        {part.text}
      </a>
    ) : (
      part.text
    )
  );
}

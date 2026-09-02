'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { SECTION_NAV_LINKS, isSectionPath } from '@/lib/sectionNav';

// Slim strip under the header: Keys · Accounts · Gift Cards · Subscriptions ·
// Rentals. Server-rendered on every page, so each section page is one link
// away from all 6,800+ product pages (SEO fix #2). Scrolls sideways on
// narrow screens instead of wrapping.
export default function SectionNav() {
  const pathname = usePathname();

  return (
    <nav className="section-nav" aria-label="Shop sections">
      <div className="container">
        <ul className="section-nav-list">
          {SECTION_NAV_LINKS.map(({ href, name }) => (
            <li key={href}>
              <Link
                href={href}
                className="section-nav-link"
                aria-current={isSectionPath(pathname, href) ? 'page' : undefined}
              >
                {name}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}

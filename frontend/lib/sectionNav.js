// The shop sections linked from every page's header strip and footer (SEO
// fix #2, 2026-09-02): the five View All pages behind the home panels. Kept
// apart from lib/categorySections.js so the header (a client component)
// does not pull that file's page copy into the browser bundle; a test
// checks the two stay in step.
export const SECTION_NAV_LINKS = [
  { href: '/keys', name: 'Keys' },
  { href: '/accounts', name: 'Accounts' },
  { href: '/gift-cards', name: 'Gift Cards' },
  { href: '/subscriptions', name: 'Subscriptions' },
  { href: '/rentals', name: 'Rentals' },
];

// True when the current URL is the section page or one of its sub-paths.
export function isSectionPath(pathname, href) {
  const current = String(pathname || '');
  return current === href || current.startsWith(`${href}/`);
}

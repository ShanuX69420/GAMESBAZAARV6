import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CATEGORY_SECTIONS } from '../lib/categorySections.js';
import { SECTION_NAV_LINKS, isSectionPath } from '../lib/sectionNav.js';

const testDir = dirname(fileURLToPath(import.meta.url));

function readProjectFile(path) {
  return readFileSync(join(testDir, '..', path), 'utf8');
}

describe('section navigation (SEO fix #2)', () => {
  it('links every section page under its registry name', () => {
    const bySlug = Object.fromEntries(CATEGORY_SECTIONS.map((section) => [section.slug, section]));

    expect(SECTION_NAV_LINKS).toHaveLength(CATEGORY_SECTIONS.length);
    for (const { href, name } of SECTION_NAV_LINKS) {
      const slug = href.replace(/^\//, '');
      expect(bySlug[slug], `${href} has no section`).toBeDefined();
      expect(name).toBe(bySlug[slug].name);
    }
  });

  it('carries the sections Google needs to reach from product pages', () => {
    expect(SECTION_NAV_LINKS.map((link) => link.href)).toEqual(
      expect.arrayContaining(['/keys', '/gift-cards', '/accounts', '/rentals']),
    );
  });

  it('marks the section and its sub-paths current, nothing else', () => {
    expect(isSectionPath('/keys', '/keys')).toBe(true);
    expect(isSectionPath('/keys/steam', '/keys')).toBe(true);
    expect(isSectionPath('/keys-and-more', '/keys')).toBe(false);
    expect(isSectionPath('/', '/keys')).toBe(false);
    expect(isSectionPath(null, '/keys')).toBe(false);
  });

  // Checked as source text: the components are JSX, which vitest cannot
  // import from a .js file.
  it('renders the same list in the header strip and the footer on every page', () => {
    expect(readProjectFile('components/SectionNav.js')).toContain('SECTION_NAV_LINKS.map(');
    expect(readProjectFile('components/Footer.js')).toContain('SECTION_NAV_LINKS.map(');
    expect(readProjectFile('components/Navbar.js')).toContain('<SectionNav />');
    expect(readProjectFile('app/layout.js')).toContain('<Navbar />');
  });
});

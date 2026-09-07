import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { looksLikeJazzNumber } from '../lib/jazzcashNetwork';

const projectRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const readProjectFile = (rel) => readFileSync(join(projectRoot, rel), 'utf8');

describe('looksLikeJazzNumber', () => {
  it('treats Jazz and Warid prefixes as Jazz', () => {
    expect(looksLikeJazzNumber('03001234567')).toBe(true);
    expect(looksLikeJazzNumber('03091234567')).toBe(true);
    expect(looksLikeJazzNumber('03211234567')).toBe(true);
    expect(looksLikeJazzNumber('0300 123 4567')).toBe(true);
  });

  it('treats Zong, Ufone and Telenor prefixes as other networks', () => {
    expect(looksLikeJazzNumber('03121234567')).toBe(false);
    expect(looksLikeJazzNumber('03331234567')).toBe(false);
    expect(looksLikeJazzNumber('03451234567')).toBe(false);
  });

  it('gives up until enough digits are typed', () => {
    expect(looksLikeJazzNumber('')).toBe(null);
    expect(looksLikeJazzNumber('030')).toBe(null);
    expect(looksLikeJazzNumber(undefined)).toBe(null);
  });
});

// The component is JSX in a .js file, which vitest does not transform here, so
// these pin the copy by reading the source — same approach as sectionNav.test.js.
describe('JazzCash approval copy', () => {
  const component = readProjectFile('components/JazzCashApprovalSteps.js');

  it('explains both ways the request can arrive', () => {
    expect(component).toContain('Jazz or Warid SIM');
    expect(component).toContain('pop-up appears on your phone screen itself');
    expect(component).toContain('Telenor, Zong, Ufone or any other SIM');
    expect(component).toContain('Account → Payment Requests → Pending');
    expect(component).toContain('Nothing arrived?');
    expect(component).toContain('Keep this page open');
  });

  it('is the one block both payment forms show while waiting', () => {
    expect(readProjectFile('app/listing/[id]/ListingDetailClient.js')).toContain('<JazzCashApprovalSteps');
    expect(readProjectFile('app/wallet/page.js')).toContain('<JazzCashApprovalSteps');
    // The old single-path wording must not creep back anywhere.
    for (const rel of ['app/listing/[id]/ListingDetailClient.js', 'app/wallet/page.js']) {
      expect(readProjectFile(rel)).not.toContain('Open your JazzCash app and approve');
    }
  });

  it('has a matching FAQ entry', () => {
    const faq = readProjectFile('app/support/faqData.js');
    expect(faq).toContain('How do I approve a JazzCash payment?');
    expect(faq).toContain('Jazz or Warid SIM');
    expect(faq).toContain('Telenor, Zong, Ufone');
  });
});

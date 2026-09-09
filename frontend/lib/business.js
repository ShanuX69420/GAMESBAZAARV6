// Single source of truth for the store's public identity. The About page and
// the sitewide Organization JSON-LD (lib/seo.js) both read from here so the
// facts never drift between pages. Deliberately no personal names anywhere:
// the business is identified as a business.
export const BUSINESS = {
  name: 'GamesBazaar',
  streetAddress: 'Block 1, Nazimabad',
  city: 'Karachi',
  region: 'Sindh',
  country: 'Pakistan',
  countryCode: 'PK',
  foundedYear: '2026',
  email: 'support@gamesbazaar.pk',
  phoneDisplay: '+92 371 2101998',
  phoneE164: '+923712101998',
  whatsappNumber: '923712101998',
  instagram: 'https://www.instagram.com/gamesbazaar.pk/',
  facebook: 'https://www.facebook.com/profile.php?id=61593041638198',
};

// One-line head-office address for footers and contact blocks.
export function headOfficeAddress() {
  return `${BUSINESS.streetAddress}, ${BUSINESS.city}, ${BUSINESS.region}, ${BUSINESS.country}`;
}

export function whatsappUrl() {
  return `https://wa.me/${BUSINESS.whatsappNumber}`;
}

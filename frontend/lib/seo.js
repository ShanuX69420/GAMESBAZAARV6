export const SITE_NAME = 'GamesBazaar';
export const DEFAULT_SITE_URL = 'http://localhost:3000';
export const DEFAULT_TITLE = "GamesBazaar - Pakistan's #1 Digital Gaming Marketplace";
export const DEFAULT_DESCRIPTION = "Buy & sell game accounts, top-ups, items, and boosting services. Pakistan's trusted gaming marketplace with secure payments and verified sellers.";

export const DEFAULT_OG_IMAGE = {
  url: '/opengraph-image',
  width: 1200,
  height: 630,
  alt: 'GamesBazaar digital gaming marketplace',
};

export function getSiteUrl() {
  return (process.env.NEXT_PUBLIC_SITE_URL || DEFAULT_SITE_URL).replace(/\/+$/, '');
}

export function absoluteUrl(path = '/') {
  return new URL(path || '/', `${getSiteUrl()}/`).toString();
}

export function canonicalPath(path = '/') {
  const value = String(path || '/').trim();
  const withSlash = value.startsWith('/') ? value : `/${value}`;
  if (withSlash === '/') return '/';
  return withSlash.replace(/\/+$/, '');
}

export function createPublicMetadata({
  title,
  description,
  path = '/',
  type = 'website',
  robots,
  openGraph = {},
  twitter = {},
}) {
  const canonical = canonicalPath(path);
  const imageUrls = [DEFAULT_OG_IMAGE.url];

  return {
    title,
    description,
    alternates: {
      canonical,
    },
    openGraph: {
      type,
      locale: 'en_US',
      siteName: SITE_NAME,
      title,
      description,
      url: canonical,
      images: [DEFAULT_OG_IMAGE],
      ...openGraph,
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description,
      images: imageUrls,
      ...twitter,
    },
    ...(robots ? { robots } : {}),
  };
}

export function organizationJsonLd() {
  return {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    name: SITE_NAME,
    url: absoluteUrl('/'),
    logo: absoluteUrl('/logo.png'),
    email: 'support@gamesbazaar.pk',
    telephone: '+92-371-2101998',
    contactPoint: [{
      '@type': 'ContactPoint',
      contactType: 'customer support',
      email: 'support@gamesbazaar.pk',
      telephone: '+92-371-2101998',
      areaServed: 'PK',
      availableLanguage: ['en', 'ur'],
    }],
  };
}

export function websiteJsonLd() {
  return {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: SITE_NAME,
    url: absoluteUrl('/'),
  };
}

export function breadcrumbJsonLd(items) {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((item, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: item.name,
      item: absoluteUrl(item.path),
    })),
  };
}

export function productJsonLd({
  name,
  description,
  path,
  image,
  sku,
  brand,
  category,
  price,
  priceCurrency = 'PKR',
  availability = 'InStock',
  sellerName,
}) {
  const url = absoluteUrl(path);

  return {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name,
    ...(description ? { description } : {}),
    // Google rejects Product markup without an image; listings have no photos
    // yet, so fall back to the stable branded image (signed R2 URLs expire).
    image: image || absoluteUrl(DEFAULT_OG_IMAGE.url),
    ...(sku ? { sku } : {}),
    ...(brand ? { brand: { '@type': 'Brand', name: brand } } : {}),
    ...(category ? { category } : {}),
    url,
    offers: {
      '@type': 'Offer',
      url,
      price,
      priceCurrency,
      availability: `https://schema.org/${availability}`,
      // Digital delivery: Google has no digital-goods variant of these offer
      // fields, so declare zero-cost/zero-day shipping and no returns.
      shippingDetails: {
        '@type': 'OfferShippingDetails',
        shippingRate: {
          '@type': 'MonetaryAmount',
          value: 0,
          currency: priceCurrency,
        },
        shippingDestination: {
          '@type': 'DefinedRegion',
          addressCountry: 'PK',
        },
        deliveryTime: {
          '@type': 'ShippingDeliveryTime',
          handlingTime: {
            '@type': 'QuantitativeValue',
            minValue: 0,
            maxValue: 0,
            unitCode: 'DAY',
          },
          transitTime: {
            '@type': 'QuantitativeValue',
            minValue: 0,
            maxValue: 0,
            unitCode: 'DAY',
          },
        },
      },
      hasMerchantReturnPolicy: {
        '@type': 'MerchantReturnPolicy',
        applicableCountry: 'PK',
        returnPolicyCategory: 'https://schema.org/MerchantReturnNotPermitted',
      },
      ...(sellerName ? { seller: { '@type': 'Person', name: sellerName } } : {}),
    },
  };
}

export function collectionPageJsonLd({ name, description, path }) {
  return {
    '@context': 'https://schema.org',
    '@type': 'CollectionPage',
    name,
    description,
    url: absoluteUrl(path),
    isPartOf: {
      '@type': 'WebSite',
      name: SITE_NAME,
      url: absoluteUrl('/'),
    },
  };
}

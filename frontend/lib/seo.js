import { BUSINESS } from '@/lib/business';

export const SITE_NAME = 'GamesBazaar';
export const DEFAULT_SITE_URL = 'http://localhost:3000';
export const DEFAULT_TITLE = "GamesBazaar - Pakistan's Digital Gaming Store";
export const DEFAULT_DESCRIPTION = "Game keys, accounts, gift cards, and subscriptions at Pakistani prices. Secure local payments, instant delivery, and easy refunds.";

export const DEFAULT_OG_IMAGE = {
  url: '/opengraph-image',
  width: 1200,
  height: 630,
  alt: 'GamesBazaar digital gaming store',
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

// One stable @id for the store, so the Product seller on every listing page
// resolves to the same Organization the root layout describes.
export function organizationId() {
  return `${absoluteUrl('/')}#organization`;
}

export function organizationJsonLd() {
  return {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    '@id': organizationId(),
    name: SITE_NAME,
    url: absoluteUrl('/'),
    logo: absoluteUrl('/logo.png'),
    description: DEFAULT_DESCRIPTION,
    foundingDate: BUSINESS.foundedYear,
    email: BUSINESS.email,
    telephone: '+92-371-2101998',
    address: {
      '@type': 'PostalAddress',
      addressLocality: BUSINESS.city,
      addressCountry: BUSINESS.countryCode,
    },
    areaServed: {
      '@type': 'Country',
      name: BUSINESS.country,
    },
    sameAs: [
      BUSINESS.instagram,
      BUSINESS.facebook,
    ],
    contactPoint: [{
      '@type': 'ContactPoint',
      contactType: 'customer support',
      email: BUSINESS.email,
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
  aggregateRating,
  reviews,
}) {
  const url = absoluteUrl(path);
  const ratingCount = Number(aggregateRating?.count) || 0;
  const reviewList = Array.isArray(reviews)
    ? reviews.filter((review) => Number.isFinite(Number(review?.rating)))
    : [];

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
    // Ratings/reviews are per-listing (this product only, never seller-wide
    // stats — Google's Product guidelines forbid store/seller ratings here)
    // and omitted entirely until the listing has at least one review.
    ...(ratingCount > 0 && Number.isFinite(Number(aggregateRating.value))
      ? {
          aggregateRating: {
            '@type': 'AggregateRating',
            ratingValue: Number(aggregateRating.value),
            reviewCount: ratingCount,
            bestRating: 5,
            worstRating: 1,
          },
        }
      : {}),
    ...(reviewList.length
      ? {
          review: reviewList.map((review) => ({
            '@type': 'Review',
            reviewRating: {
              '@type': 'Rating',
              ratingValue: Number(review.rating),
              bestRating: 5,
              worstRating: 1,
            },
            author: {
              '@type': 'Person',
              name: review.author || 'GamesBazaar buyer',
            },
            ...(review.date ? { datePublished: review.date } : {}),
            ...(review.body ? { reviewBody: review.body } : {}),
          })),
        }
      : {}),
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
      // Every item is sold by the store itself (direct shop since 2026-08), so
      // the seller is the Organization — never a Person / marketplace vendor.
      seller: {
        '@type': 'Organization',
        '@id': organizationId(),
        name: SITE_NAME,
        url: absoluteUrl('/'),
      },
    },
  };
}

export function faqPageJsonLd(faqCategories) {
  const questions = faqCategories.flatMap((faqCategory) => faqCategory.questions || []);
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: questions.map((item) => ({
      '@type': 'Question',
      name: item.q,
      acceptedAnswer: {
        '@type': 'Answer',
        text: item.a,
      },
    })),
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

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

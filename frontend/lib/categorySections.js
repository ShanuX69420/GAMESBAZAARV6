// The four home "Popular" panels and their View All pages. Slugs must match
// both the backend section registry (HOME_POPULAR_SECTIONS) and the app
// routes: /accounts, /top-ups, /offline-activation, /gift-cards.
export const CATEGORY_SECTIONS = [
  {
    slug: 'accounts',
    name: 'Accounts',
    heading: 'All Game Accounts',
    title: 'Buy Game Accounts',
    description:
      'Browse every game with accounts for sale on GamesBazaar. Buy game accounts in PKR from verified sellers with secure payments and buyer protection.',
  },
  {
    slug: 'top-ups',
    name: 'Top Ups',
    heading: 'All Top Ups',
    title: 'Buy Game Top-Ups',
    description:
      'Browse every game with top-ups on GamesBazaar — PUBG Mobile UC, Free Fire Diamonds, and more. Fast delivery, PKR pricing, and buyer protection.',
  },
  {
    slug: 'offline-activation',
    name: 'Offline Activation',
    heading: 'All Offline Activation Games',
    title: 'Offline Activation Games',
    description:
      'Browse every game available with offline activation on GamesBazaar. Play top PC titles for less, with fast delivery and PKR pricing from verified sellers.',
  },
  {
    slug: 'gift-cards',
    name: 'Gift Cards',
    heading: 'All Gift Cards',
    title: 'Buy Gift Cards',
    description:
      'Browse every gift card on GamesBazaar — Steam Wallet, PlayStation, Nintendo, and more across many regions. Fast delivery and PKR pricing.',
  },
];

export function getCategorySection(slug) {
  return CATEGORY_SECTIONS.find((section) => section.slug === slug);
}

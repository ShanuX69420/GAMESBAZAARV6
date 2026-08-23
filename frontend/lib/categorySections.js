// The home "Popular" panels and their View All pages. Slugs must match
// both the backend section registry (HOME_POPULAR_SECTIONS) and the app
// routes: /keys, /accounts, /top-ups, /gift-cards.
export const CATEGORY_SECTIONS = [
  {
    slug: 'keys',
    name: 'Keys',
    heading: 'All Game Keys',
    title: 'Buy Game Keys',
    description:
      'Browse every game with keys for sale on GamesBazaar — Steam, PSN, Xbox and more. Buy game keys in PKR with instant delivery and easy refunds.',
  },
  {
    slug: 'accounts',
    name: 'Accounts',
    heading: 'All Game Accounts',
    title: 'Buy Game Accounts',
    description:
      'Browse every game with accounts for sale on GamesBazaar. Buy game accounts in PKR with secure payments and easy refunds.',
  },
  {
    slug: 'top-ups',
    name: 'Top Ups',
    heading: 'All Top Ups',
    title: 'Buy Game Top-Ups',
    description:
      'Browse every game with top-ups on GamesBazaar — PUBG Mobile UC, Free Fire Diamonds, and more. Fast delivery, PKR pricing, and easy refunds.',
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

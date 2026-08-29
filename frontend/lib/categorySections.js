// The home "Popular" panels and their View All pages. Slugs must match
// both the backend section registry (HOME_POPULAR_SECTIONS) and the app
// routes: /keys, /accounts, /top-ups, /gift-cards, /rentals.
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
    title: 'Buy Game Accounts in Pakistan – Fresh & Full Access',
    description:
      'Fresh, full-access game accounts at Pakistani prices. Change the email and password — the account is yours. Pay by JazzCash, Easypaisa or bank transfer.',
    seoText: `## Buy game accounts in Pakistan

GamesBazaar sells ready-to-play game accounts for hundreds of titles — everything in the A–Z list above has a live PKR price next to it. There are no dollar rates and no international card requirements: you pay in rupees with JazzCash, Easypaisa or bank transfer, and your account arrives in the order chat right here on the site.

An account is often the cheapest way to own a game in Pakistan. Instead of paying the direct store price, you buy a freshly created account that already has the game purchased on it — older titles start at a few hundred rupees, and even new releases usually cost well under their store price.

## What "full access" means

Most accounts here are freshly created for sale, with the game bought onto them — nobody has played on them before you. Full access means you receive both logins: the account's username and password, plus the login for the email address attached to it. Change both after delivery and the account is permanently yours. Each listing states the exact edition, platform and delivery time before you pay, so what's written on the listing is exactly what you get.

## How delivery works

Pick a game from the list, choose a listing, and pay at the Buy button. Your login details are sent through the order chat — most accounts arrive within minutes, and every listing shows its own delivery time up front. Log in, set your new password and email, and start downloading. If anything doesn't match the listing, message us in the order chat: problems get fixed fast, and refunds are easy when we can't put it right. The reviews on this page are from real delivered orders.`,
    faq: [
      {
        q: 'Is it safe to buy a game account in Pakistan?',
        a: 'Buying from a stranger on a classifieds site means trusting a secondhand account that can be pulled back. GamesBazaar works differently: accounts are freshly made for sale, you get the attached email as well as the account login, and our team is one message away in the order chat if anything needs fixing.',
      },
      {
        q: "Can I change the account's email and password?",
        a: "Yes. Full access includes the email login, so you can move the account to your own details the moment it arrives. Once you've changed them, you hold every login there is.",
      },
      {
        q: 'Can the previous owner take the account back?',
        a: 'A fresh account has no previous owner — it is created new and the game is bought onto it before sale. Change the password and email after delivery and no one else can sign in.',
      },
      {
        q: 'How fast will I get my account?',
        a: 'Every listing shows its delivery time before you pay, and most accounts are delivered to your order chat within minutes of payment.',
      },
      {
        q: 'How do I pay?',
        a: 'All prices are in Pakistani rupees. You can pay with JazzCash, Easypaisa or bank transfer — no international card needed.',
      },
      {
        q: 'Can I add my own games and funds to the account?',
        a: "Yes — after you change the login details, it's your account to use like any other. If your listing includes a setup note, such as waiting for the store region to update before adding funds, follow it to keep the account in good standing.",
      },
    ],
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
  {
    slug: 'rentals',
    name: 'Rentals',
    heading: 'All Game Rentals',
    title: 'Rent PS4 & PS5 Games',
    description:
      'Rent PlayStation games on GamesBazaar — play PS4 and PS5 titles for a week or a month at a fraction of the price of buying. PKR pricing, fast delivery, easy refunds.',
  },
];

export function getCategorySection(slug) {
  return CATEGORY_SECTIONS.find((section) => section.slug === slug);
}

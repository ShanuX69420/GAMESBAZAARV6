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
    title: 'Game Top-Ups in Pakistan – PUBG UC, Diamonds & More',
    description:
      'Top up PUBG UC, Free Fire Diamonds and more at PKR prices — no password, just your player ID. Pay with JazzCash, Easypaisa or bank transfer. Fast delivery.',
    seoText: `## Game top-ups in Pakistan

Diamonds, UC, CP, coins and gaming subscriptions — this page lists every game GamesBazaar can top up, from PUBG Mobile and Free Fire to Mobile Legends and Yalla Ludo. Prices are in rupees and start from pocket-money packs, so you can load exactly as much as you need. Pay with JazzCash, Easypaisa or bank transfer — no dollar card required.

## Your account stays yours — no password needed

A top-up here is a direct credit to your own game account through official channels. You give us the ID printed under your in-game nickname — a Player ID, Character ID or user ID — and the diamonds or UC land in your account at full store value. Nobody asks for your password, and you never hand over your login. Many packs are credited automatically the moment you pay: enter your ID at checkout and the top-up starts on its own. The rest are delivered by our team, with confirmation in your order chat.

## Picking the right pack

Some games care about region and some don't. Free Fire diamonds, for example, come in region versions — including Pakistan — so use the Region filter and match it to where your account was created. Mobile Legends needs your ID plus the Server ID shown in brackets under your name. Subscription products state their account-region requirements on the listing. Whatever you pick, the listing spells out exactly what to enter and how long delivery takes before you pay — and live PKR prices for every game are in the list above.`,
    faq: [
      {
        q: 'How does a game top-up work on GamesBazaar?',
        a: "Choose your game from the list, pick a pack, and enter your player ID at checkout (or send it in the order chat if the listing asks). We credit the amount directly to your account and confirm in the chat when it's done.",
      },
      {
        q: 'Is it safe to top up my account this way?',
        a: 'Yes — top-ups are bought from the official store and credited by ID. You never share a password or log in anywhere, so your account login never leaves your hands.',
      },
      {
        q: 'Do you have Free Fire top-up for Pakistan region?',
        a: 'Yes. Free Fire diamonds come in region versions, Pakistan included. Use the Region filter on the Free Fire page and pick the region your account was created in.',
      },
      {
        q: 'How fast will I get my diamonds or UC?',
        a: 'Many packs are credited automatically right after payment. Every listing shows its own delivery time before you buy, and most orders finish within minutes.',
      },
      {
        q: 'How do I pay?',
        a: 'In rupees, with JazzCash, Easypaisa or bank transfer. No international card, no dollar conversion.',
      },
      {
        q: "What if my top-up doesn't arrive?",
        a: "Message us in the order chat — problems get fixed fast, and if we can't deliver what you paid for, refunds are easy. The reviews on this page come from real delivered orders.",
      },
    ],
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

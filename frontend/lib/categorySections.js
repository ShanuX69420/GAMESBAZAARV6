// The home "Popular" panels and their View All pages. Slugs must match
// both the backend section registry (HOME_POPULAR_SECTIONS) and the app
// routes: /keys, /accounts, /subscriptions, /gift-cards, /rentals.
// Direct game top-ups were retired 2026-09-02: /top-ups now redirects to
// /subscriptions, the home of the PS Plus and Game Pass codes.
export const CATEGORY_SECTIONS = [
  {
    slug: 'keys',
    name: 'Keys',
    heading: 'All Game Keys',
    title: 'Buy Game Keys in Pakistan – Steam Keys & Gifts',
    description:
      'Official Steam keys at rupee prices, delivered instantly — plus Pakistan-region Steam gifts. Pay in PKR by JazzCash, Easypaisa or bank transfer.',
    seoText: `## Buy game keys in Pakistan

Every game in the A–Z list above has key listings with live rupee prices — no dollar conversions, no international card, and nothing to wait for: your key is delivered automatically in the order chat the moment payment goes through. Redeem it on your own Steam account and the game is yours for good.

## One page, two ways to buy: keys and gifts

Listings here come in two forms, and the Method filter at the top switches between them. A Digital Key is a code you redeem yourself — global, so it activates on any Steam account in any country. As a Gift sends the game straight into your Steam library instead: you drop your Steam friend invite link at checkout, you're added automatically, and the game arrives as a gift — no code to type. Gifts are for Pakistan-region Steam accounts only, so check your account region before ordering. Either way the game lands in your own library, with your progress and achievements, permanently.

## Why buy from GamesBazaar

Foreign key sites price in dollars and expect a card that works internationally; classified ads hand you a code with no comeback if it fails. GamesBazaar sells official keys at rupee prices — paid with JazzCash, Easypaisa or bank transfer — and stays reachable afterwards: if a key doesn't activate, message us in the order chat and we'll fix it fast or refund you. Real reviews from delivered orders appear right on this page, and the letters up top jump you straight to any game in the catalogue.`,
    faq: [
      {
        q: 'How do I redeem a Steam key?',
        a: 'Open Steam, click "Add a Game" in the bottom-left corner, choose "Activate a Product on Steam", and enter your key — the game downloads to your library. The key itself arrives in your order chat automatically after payment.',
      },
      {
        q: 'What is the difference between a Steam key and a Steam gift?',
        a: "A key is a code you activate yourself, and it works on accounts in any country. A gift skips the code: we send the game to your library through Steam's own gifting system using your friend invite link. Gifts only work on Pakistan-region accounts.",
      },
      {
        q: 'Will a global key work on my Pakistani Steam account?',
        a: 'Yes. Keys sold here are marked Global, which means they activate on any Steam account regardless of country — Pakistan included.',
      },
      {
        q: 'What do I need to buy a game as a Steam gift?',
        a: "Your Steam friend invite link (in Steam: Friends → Add a Friend → copy your invite link) and a Pakistan-region account. Enter the link at checkout — you're added automatically and the game arrives in your library as a gift.",
      },
      {
        q: 'How do I pay?',
        a: 'All prices are in rupees. JazzCash, Easypaisa and bank transfer all work — no dollar card needed.',
      },
      {
        q: "What if my key doesn't activate?",
        a: "Tell us in the order chat. Problems get fixed fast, and when we can't put a working key in your hands, refunds are easy.",
      },
    ],
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
    slug: 'subscriptions',
    name: 'Subscriptions',
    heading: 'All Subscriptions',
    title: 'PS Plus & Xbox Game Pass in Pakistan – Subscription Codes',
    description:
      'PlayStation Plus and Xbox Game Pass membership codes at rupee prices, by tier, duration and region. Pay with JazzCash, Easypaisa or bank transfer.',
    seoText: `## Gaming subscriptions in Pakistan, priced in rupees

PlayStation Plus and Xbox Game Pass are sold here as membership codes. Pick the tier and duration from the brand's page, pay in rupees with JazzCash, Easypaisa or bank transfer, and redeem the code on your own account. There is no international card and no dollar conversion, and nobody ever needs your login — you enter the code yourself and the membership appears on your console.

## Match the code to your account's store region

Subscription codes are region-locked. A PlayStation Plus code redeems only on an account registered to the matching PlayStation Store, and Game Pass codes work the same way on Xbox. Check which store your account belongs to in its settings, then use the Region filter on the brand's page and pick the code that matches. Every listing states its region, tier and duration before you pay, and the PlayStation and Xbox pages explain which versions suit accounts commonly used in Pakistan.

## Codes arrive in your order chat

Each listing shows its own delivery time before you buy, and most codes are delivered in the order chat within minutes of payment. Redeem it on your console or in the platform's app and the membership starts on that account straight away. If a code we sold does not redeem, message us in the order chat — we help you check the region first, fix what we can, and refund you when the code is at fault. The reviews on this page come from delivered orders.`,
    faq: [
      {
        q: 'How do I redeem a PlayStation Plus code?',
        a: 'Open the PlayStation Store on your console or in the PlayStation app, choose Redeem Codes, and enter the code. The membership starts on that account immediately. The code must match the region your account is registered in.',
      },
      {
        q: 'How do I redeem an Xbox Game Pass code?',
        a: 'On your Xbox open the Store and choose Redeem, or sign in at redeem.microsoft.com with the account you play on and enter the code there. Buy the region version that matches your Microsoft account.',
      },
      {
        q: 'Which region should I buy?',
        a: "The region your account is registered in — not the country you live in. It's in your account settings on the console. Match it with the Region filter on the PlayStation or Xbox page before you pay.",
      },
      {
        q: 'Can I redeem a code if I already have a membership?',
        a: "Usually yes: a code for the same tier adds its time to the end of your current membership. Switching tiers follows the platform's own conversion rules, so read the store's message before you confirm.",
      },
      {
        q: 'How do I pay?',
        a: 'In rupees, with JazzCash, Easypaisa or bank transfer. No international card, no dollar conversion.',
      },
      {
        q: "What if my code doesn't work?",
        a: "Message us in the order chat and we'll work out what happened — a region mismatch is the usual cause, and we help you check. Problems get fixed fast, and refunds are easy when a code we sold is at fault.",
      },
    ],
  },
  {
    slug: 'gift-cards',
    name: 'Gift Cards',
    heading: 'All Gift Cards',
    title: 'Buy Gift Cards in Pakistan – Steam, PSN, iTunes',
    description:
      'Steam Wallet, PSN, iTunes, Google Play and more at rupee prices, in dozens of regions. Codes arrive in minutes — pay via JazzCash, Easypaisa or bank transfer.',
    seoText: `## Gift cards in Pakistan, priced in rupees

Steam Wallet codes, PlayStation Store cards, App Store & iTunes, Google Play, Roblox, Razer Gold — every brand in the list above is sold in rupees, with live prices on this page and denominations that start small enough to try. You don't need an international credit card for any of it: pay via JazzCash, Easypaisa or bank transfer and the code is yours.

Most shops in Pakistan stock a handful of US, UK and UAE cards. GamesBazaar carries the same brands in dozens of region versions — so whether your account lives on the US store, the UAE store or somewhere less common, there's usually a card here that matches it.

## The one rule: match the region

Gift-card codes are region-locked. A card made for one country's store will not redeem on an account registered in another, and that single mistake causes almost every failed redemption. So before you buy, check which region your account is registered in — it's in your account settings on every platform — then use the Region filter on the brand's page to pick the matching card. Steam is the one exception worth knowing: its codes follow the store currency rather than the country, and each Steam listing spells out exactly which accounts it fits.

## Codes arrive the moment you pay

There's no waiting on a person for most cards: the code is delivered automatically in your order chat right after payment. You redeem it yourself on your own account — nobody ever needs your login — and the balance appears instantly. Every code is genuine and bought from official channels, the redeem steps are written on each listing, and if anything goes sideways we're one message away in the order chat. The reviews you can read on this page all come from delivered orders.`,
    faq: [
      {
        q: 'How can I buy a gift card in Pakistan without a credit card?',
        a: 'Every card here is priced in rupees and paid for with JazzCash, Easypaisa or bank transfer. No international card, no PayPal, no dollar conversion — pick a card, pay locally, and the code arrives in your order chat.',
      },
      {
        q: 'Which region gift card should I buy?',
        a: "The region your account is registered in — not the country you live in. Check your account settings on the platform first, then match it with the Region filter on the brand's page. If your PlayStation account is on the US store, buy a US card, and so on.",
      },
      {
        q: 'Will a gift card work on my Pakistani account?',
        a: "That depends on the platform and the card. The card's region (or for Steam, its currency) has to match your account, and every listing states its region clearly before you pay. Each brand's page explains which versions suit accounts commonly used in Pakistan.",
      },
      {
        q: 'How fast will I get my code?',
        a: 'Most codes are delivered automatically in the order chat seconds after payment goes through. Each listing shows its delivery time before you buy.',
      },
      {
        q: 'Are the codes genuine?',
        a: 'Yes — codes come from official channels and you redeem them yourself on your own account, so you see the balance land with your own eyes. The reviews on this page are from real delivered orders.',
      },
      {
        q: "What if my code doesn't redeem?",
        a: "Message us in the order chat and we'll work out what happened — a region mismatch is the usual cause, and we help you check. Problems get fixed fast, and refunds are easy when a code we sold is at fault.",
      },
    ],
  },
  {
    slug: 'rentals',
    name: 'Rentals',
    heading: 'All Game Rentals',
    title: 'Rent PS4 & PS5 Games in Pakistan – Play in Minutes',
    description:
      'Rent PS4 & PS5 games for 7 to 30 days at a fraction of the buying price — digital, no discs, set up in minutes. Pay by JazzCash, Easypaisa or bank transfer.',
    seoText: `## Rent PlayStation games in Pakistan

Why pay thousands for a game you'll finish in a week? GamesBazaar rents PS4 and PS5 games for 7 to 30 days at a fraction of the price of buying — rupee prices, paid with JazzCash, Easypaisa or bank transfer. The A–Z list above covers hundreds of titles, from this year's releases to back-catalogue classics, each with live prices and a Rental Period filter on its page.

## How renting works

There are no discs and nothing to collect. A rental gives you sign-in access to a PlayStation account that owns the game: log in on your own console, download the game, and play the full version for your rental period. When the time is up the game stops working — and if you rent the same game again later, your saves carry on where you left off. Need longer? Extensions are arranged in the order chat before your rental ends. Most rentals are set up and playing in well under an hour.

## The fine print, upfront

Rentals have rules, and we'd rather you know them before you pay. You play on the rented profile, so saves and trophies live there rather than on your own PSN profile — your own account, games and saves are never touched. An internet connection is required while playing, and rentals are single-player only: online multiplayer isn't supported. The account you're lent must stay as it is — changing its password or email ends the rental. In return, the promise is simple: if the game stops working during your rental through no fault of yours, we fix it or refund the remaining time.`,
    faq: [
      {
        q: 'How does renting a PlayStation game work?',
        a: 'You get sign-in access to a PlayStation account that owns the game. Log in on your PS4 or PS5 — rentals work on both — download the game, and play the full version for the period you paid for.',
      },
      {
        q: 'How fast can I start playing?',
        a: 'Sign-in details arrive in your order chat after payment, and most rentals are set up and playing in well under an hour.',
      },
      {
        q: 'Do I keep the game or my saves?',
        a: "The game stops working when your rental period ends — that's what makes it so much cheaper than buying. Your saves stay on the rented profile, though, so if you rent the same game again later you continue where you left off. You can also extend from the order chat before the period ends.",
      },
      {
        q: 'Can I play online multiplayer?',
        a: 'No — rentals are single-player only. You do still need an internet connection while playing.',
      },
      {
        q: 'Is my own PlayStation account at risk?',
        a: 'No. You never hand over your own account — you sign in to a separate one next to it. Your profile, your games and your saves are untouched, and when the rental ends you simply stop using the rented account.',
      },
      {
        q: 'What if the game stops working during my rental?',
        a: "Message us in the order chat. If it stopped through no fault of yours, we fix it or refund the time you had left. Just keep the rented account as you received it — changing its password or email ends the rental.",
      },
    ],
  },
];

export function getCategorySection(slug) {
  return CATEGORY_SECTIONS.find((section) => section.slug === slug);
}

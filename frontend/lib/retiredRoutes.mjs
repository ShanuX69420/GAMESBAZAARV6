// Retired catalog URLs and where they live now.
//
// Built from the deletion backups in tools/archive (offline-activation
// category removed 2026-08-23; direct top-ups + six gift-card brands removed
// 2026-09-02) and every destination was checked against the production API
// on 2026-09-02. Kept as plain data so next.config.mjs stays readable and the
// vitest suite can assert on it. Redirects are matched in array order, so the
// per-game offline-activation exceptions must stay ABOVE the wildcard rule.
//
// Rule of thumb for the destination: the same game's gift-cards page for a
// retired top-up / gift-card page, the same game's keys page for a retired
// offline-activation page, otherwise the game's busiest remaining page, and
// the section page (/gift-cards or /keys) when the game has nothing left.

// 32 game+category pages deleted outright on 2026-09-02 (26 top-up pages,
// 6 gift-card brands).
export const RETIRED_PAGE_REDIRECTS = [
  { source: '/games/8-ball-pool/cash', destination: '/gift-cards' },
  { source: '/games/age-of-empires-mobile/top-ups', destination: '/gift-cards' },
  { source: '/games/arena-breakout/top-ups', destination: '/gift-cards' },
  { source: '/games/arena-breakout/gift-cards', destination: '/gift-cards' },
  { source: '/games/arena-breakout-infinite/top-ups', destination: '/gift-cards' },
  { source: '/games/asphalt-9-legends/top-ups', destination: '/gift-cards' },
  { source: '/games/bigo-live/top-ups', destination: '/games/bigo-live/gift-cards' },
  { source: '/games/blood-strike/top-ups', destination: '/gift-cards' },
  { source: '/games/call-of-duty-mobile/cp', destination: '/gift-cards' },
  { source: '/games/delta-force/top-ups', destination: '/gift-cards' },
  { source: '/games/ea-fc-26/gift-cards', destination: '/games/ea-fc-26/rentals' },
  { source: '/games/fc-mobile/top-ups', destination: '/gift-cards' },
  { source: '/games/free-fire/diamonds', destination: '/games/free-fire/gift-cards' },
  { source: '/games/garena-undawn/top-ups', destination: '/gift-cards' },
  { source: '/games/genshin-impact/top-ups', destination: '/gift-cards' },
  { source: '/games/honkai-star-rail/top-ups', destination: '/gift-cards' },
  { source: '/games/ludo-club/top-ups', destination: '/gift-cards' },
  { source: '/games/mangatoon/top-ups', destination: '/gift-cards' },
  { source: '/games/marvel-rivals/top-ups', destination: '/gift-cards' },
  { source: '/games/mobile-legends-bang-bang/top-ups', destination: '/games/mobile-legends-bang-bang/gift-cards' },
  { source: '/games/netflix/gift-cards', destination: '/gift-cards' },
  { source: '/games/oxide-survival-island/top-ups', destination: '/gift-cards' },
  { source: '/games/pubg-mobile/uc', destination: '/games/pubg-mobile/gift-cards' },
  { source: '/games/rainbow-six-mobile/top-ups', destination: '/gift-cards' },
  { source: '/games/the-division-resurgence/top-ups', destination: '/gift-cards' },
  { source: '/games/twitch/gift-cards', destination: '/gift-cards' },
  { source: '/games/undawn/top-ups', destination: '/gift-cards' },
  { source: '/games/wild-rift/gift-cards', destination: '/gift-cards' },
  { source: '/games/world-of-warcraft/gift-cards', destination: '/gift-cards' },
  { source: '/games/wuthering-waves/top-ups', destination: '/gift-cards' },
  { source: '/games/yalla-ludo/top-ups', destination: '/games/yalla-ludo/gift-cards' },
  { source: '/games/zenless-zone-zero/top-ups', destination: '/gift-cards' },
];

// Four of those pages carried a renamed URL (uc, diamonds, cash, cp) but the
// backend also answered the plain category slug, so /games/<game>/top-ups was
// a live, self-canonical alias that search engines could have indexed.
export const RETIRED_PAGE_ALIAS_REDIRECTS = [
  { source: '/games/pubg-mobile/top-ups', destination: '/games/pubg-mobile/gift-cards' },
  { source: '/games/free-fire/top-ups', destination: '/games/free-fire/gift-cards' },
  { source: '/games/8-ball-pool/top-ups', destination: '/gift-cards' },
  { source: '/games/call-of-duty-mobile/top-ups', destination: '/gift-cards' },
];

// Games whose only pages were among the 32 above; /games/<slug> now renders
// an empty "no categories" shell, so send it to the section page instead.
export const EMPTY_GAME_REDIRECTS = [
  { source: '/games/8-ball-pool', destination: '/gift-cards' },
  { source: '/games/age-of-empires-mobile', destination: '/gift-cards' },
  { source: '/games/arena-breakout', destination: '/gift-cards' },
  { source: '/games/arena-breakout-infinite', destination: '/gift-cards' },
  { source: '/games/asphalt-9-legends', destination: '/gift-cards' },
  { source: '/games/blood-strike', destination: '/gift-cards' },
  { source: '/games/garena-undawn', destination: '/gift-cards' },
  { source: '/games/honkai-star-rail', destination: '/gift-cards' },
  { source: '/games/ludo-club', destination: '/gift-cards' },
  { source: '/games/mangatoon', destination: '/gift-cards' },
  { source: '/games/netflix', destination: '/gift-cards' },
  { source: '/games/oxide-survival-island', destination: '/gift-cards' },
  { source: '/games/rainbow-six-mobile', destination: '/gift-cards' },
  { source: '/games/the-division-resurgence', destination: '/gift-cards' },
  { source: '/games/twitch', destination: '/gift-cards' },
  { source: '/games/undawn', destination: '/gift-cards' },
  { source: '/games/wild-rift', destination: '/gift-cards' },
  { source: '/games/world-of-warcraft', destination: '/gift-cards' },
  { source: '/games/wuthering-waves', destination: '/gift-cards' },
  { source: '/games/zenless-zone-zero', destination: '/gift-cards' },
];

// Offline-activation pages whose game has no keys page: go to the game's
// busiest remaining page, or the /keys section when nothing is left.
export const OFFLINE_ACTIVATION_EXCEPTIONS = [
  { source: '/games/alan-wake-2/offline-activation', destination: '/games/alan-wake-2/rentals' },
  { source: '/games/alien-rogue-incursion/offline-activation', destination: '/keys' },
  { source: '/games/battlefield-1942/offline-activation', destination: '/keys' },
  { source: '/games/battlefield-bad-company-2/offline-activation', destination: '/keys' },
  { source: '/games/call-of-duty-1/offline-activation', destination: '/games/call-of-duty-1/accounts' },
  { source: '/games/call-of-duty-2/offline-activation', destination: '/games/call-of-duty-2/accounts' },
  { source: '/games/call-of-duty-modern-warfare-3-2011/offline-activation', destination: '/games/call-of-duty-modern-warfare-3-2011/accounts' },
  { source: '/games/call-of-duty-modern-warfare-4/offline-activation', destination: '/games/call-of-duty-modern-warfare-4/accounts' },
  { source: '/games/civilization-3/offline-activation', destination: '/games/civilization-3/accounts' },
  { source: '/games/civilization-4/offline-activation', destination: '/games/civilization-4/accounts' },
  { source: '/games/civilization-5/offline-activation', destination: '/games/civilization-5/accounts' },
  { source: '/games/command-conquer/offline-activation', destination: '/games/command-conquer/accounts' },
  { source: '/games/dragon-ball-sparking-zero/offline-activation', destination: '/games/dragon-ball-sparking-zero/accounts' },
  { source: '/games/ea-app/offline-activation', destination: '/games/ea-app/gift-cards' },
  { source: '/games/ea-fc-24/offline-activation', destination: '/games/ea-fc-24/rentals' },
  { source: '/games/epic-games/offline-activation', destination: '/keys' },
  { source: '/games/farming-simulator/offline-activation', destination: '/games/farming-simulator/rentals' },
  { source: '/games/fifa/offline-activation', destination: '/games/fifa/rentals' },
  { source: '/games/final-fantasy-xvi/offline-activation', destination: '/games/final-fantasy-xvi/rentals' },
  { source: '/games/football-manager-2024/offline-activation', destination: '/keys' },
  { source: '/games/mimesis/offline-activation', destination: '/keys' },
  { source: '/games/only-up/offline-activation', destination: '/games/only-up/accounts' },
  { source: '/games/other-games/offline-activation', destination: '/keys' },
  { source: '/games/watch-dogs-2/offline-activation', destination: '/games/watch-dogs-2/rentals' },
];

// Every other /games/<game>/offline-activation URL (266 pages at retirement)
// lands on that game's keys page.
export const OFFLINE_ACTIVATION_WILDCARD = {
  source: '/games/:game/offline-activation',
  destination: '/games/:game/keys',
};

export function retiredRedirects() {
  return [
    ...RETIRED_PAGE_REDIRECTS,
    ...RETIRED_PAGE_ALIAS_REDIRECTS,
    ...EMPTY_GAME_REDIRECTS,
    ...OFFLINE_ACTIVATION_EXCEPTIONS,
    OFFLINE_ACTIVATION_WILDCARD,
  ].map((entry) => ({ ...entry, permanent: true }));
}

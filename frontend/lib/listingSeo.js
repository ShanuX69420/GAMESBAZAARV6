import { SITE_NAME } from '@/lib/seo';

// Google and Ahrefs both treat ~60 characters as the visible title budget.
export const SEO_TITLE_MAX_LENGTH = 60;
const TITLE_TEMPLATE_SUFFIX = ` | ${SITE_NAME}`;

export function cleanText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function containsIgnoringCase(haystack, needle) {
  if (!haystack || !needle) return false;
  return haystack.toLowerCase().includes(needle.toLowerCase());
}

// "Gift Cards" -> "Gift Card", "Top Ups" -> "Top Up"; leaves "Game Pass",
// "Robux", "UC" alone. Only used for the category word we append.
export function singularize(value) {
  const text = cleanText(value);
  if (text.length >= 4 && /s$/i.test(text) && !/ss$/i.test(text)) {
    return text.slice(0, -1);
  }
  return text;
}

function hasTypeFilter(listing) {
  const filters = listing?.filter_display;
  if (!filters || typeof filters !== 'object') return false;
  return Object.keys(filters).some((name) => cleanText(name).toLowerCase() === 'type');
}

/**
 * Listing name for <title>, description and Product JSON-LD.
 *
 * Offer-mode listings (gift cards, top-ups) are titled by denomination only:
 * "5 USD (Argentina)", "60 UC". Thirteen brands share "50 USD (USA)", so the
 * page titles were near-duplicates (Ahrefs 2026-09-02). Prefix the game or
 * brand and, when the title does not already say what the thing is, append
 * the singular category word: "Steam 5 USD (Argentina) Gift Card",
 * "PUBG Mobile 60 UC", "Xbox 1 Month (USA) Game Pass".
 *
 * Standard and currency listings already carry the game in their title
 * (rentals, keys, accounts) and are left exactly as written.
 */
export function listingDisplayName(listing) {
  const title = cleanText(listing?.title);
  if (!title) return '';
  if (cleanText(listing?.listing_mode) !== 'offer') return title;

  const game = cleanText(listing?.game_name);
  const parts = [];
  if (game && !containsIgnoringCase(title, game)) parts.push(game);
  parts.push(title);

  // Pages with a "Type" dropdown sell more than one product under a single
  // category label (PUBG's UC page also lists WOW Coins) — the label would be
  // wrong on half the listings there, so leave it off.
  const categoryWord = singularize(listing?.category_name);
  if (
    categoryWord
    && !hasTypeFilter(listing)
    && !containsIgnoringCase(title, categoryWord)
    && !containsIgnoringCase(game, categoryWord)
  ) {
    parts.push(categoryWord);
  }

  return parts.join(' ');
}

/**
 * <title> for a listing page. The root layout appends " | GamesBazaar"; when
 * that would push the title past the visible budget the brand suffix is the
 * least valuable part, so the title is emitted as-is (absolute) instead.
 */
export function listingPageTitle({ name, price }) {
  const title = price ? `${name} - ${price}` : name;
  const fitsTemplate = (title + TITLE_TEMPLATE_SUFFIX).length <= SEO_TITLE_MAX_LENGTH;
  return { title, absolute: !fitsTemplate };
}

function slugText(value) {
  const slug = cleanText(value);
  return /^[\w-]+$/.test(slug) ? slug : '';
}

/**
 * Home › Game › Category trail for a listing page (SEO fix #2, 2026-09-02).
 *
 * Every crumb carries the page it points at; the listing page renders those
 * as links and the layout folds the same trail into BreadcrumbList JSON-LD.
 * The game and category slugs arrived with this fix — a payload cached
 * before it carries the names only, and those crumbs come back with a null
 * path so the page shows them as plain text instead of a broken link.
 */
export function listingBreadcrumbs(listing) {
  const crumbs = [{ name: 'Home', path: '/' }];
  const gameName = cleanText(listing?.game_name);
  const categoryName = cleanText(listing?.category_name);
  const gameSlug = slugText(listing?.game_slug);
  const categorySlug = slugText(listing?.category_slug);
  const gamePath = gameSlug ? `/games/${encodeURIComponent(gameSlug)}` : null;

  if (gameName) crumbs.push({ name: gameName, path: gamePath });
  if (categoryName) {
    crumbs.push({
      name: categoryName,
      path: gamePath && categorySlug ? `${gamePath}/${encodeURIComponent(categorySlug)}` : null,
    });
  }
  return crumbs;
}

/**
 * The BreadcrumbList trail for a listing page: Home › "<Game> <Category>" ›
 * (the listing, appended by the layout). The visible trail also links the
 * game, but /games/<slug> always redirects to the game's busiest page and a
 * schema URL has to be a final one — so the game item is left out and the
 * category item is named after the page it points at ("Elden Ring Keys",
 * that page's own title). Null until the payload carries the page slugs.
 */
export function listingSchemaBreadcrumbs(listing) {
  const trail = listingBreadcrumbs(listing);
  if (trail.length !== 3 || !trail[2].path) return null;
  return [
    trail[0],
    { name: cleanText(`${trail[1].name} ${trail[2].name}`), path: trail[2].path },
  ];
}

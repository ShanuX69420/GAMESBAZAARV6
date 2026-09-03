// Games worth browsing to: only those with at least one active listing.
// A game whose pages are all empty (or that lost its last page — e.g. the
// retired top-up games) would be a dead end from a directory, and its
// category pages are noindexed anyway. Until any game has stock, fall back
// to the full catalog so the page never renders empty.
export function stockedGamesOrAll(games) {
  const stocked = games.filter((game) => (game.listing_count || 0) > 0);
  return stocked.length > 0 ? stocked : games;
}

export function groupGamesByAlphabet(games) {
  const sorted = [...games].sort((a, b) => a.name.localeCompare(b.name));
  const groups = {};

  for (const game of sorted) {
    const firstChar = game.name.trim().charAt(0).toUpperCase();
    const key = /^[A-Z]$/.test(firstChar) ? firstChar : '#';
    if (!groups[key]) groups[key] = [];
    groups[key].push(game);
  }

  // Order: # (numbers, symbols, and non-Latin headings) first, then A-Z.
  const orderedKeys = [];
  if (groups['#']) orderedKeys.push('#');
  for (let i = 65; i <= 90; i++) {
    const letter = String.fromCharCode(i);
    if (groups[letter]) orderedKeys.push(letter);
  }

  return orderedKeys.map((key) => ({ letter: key, games: groups[key] }));
}

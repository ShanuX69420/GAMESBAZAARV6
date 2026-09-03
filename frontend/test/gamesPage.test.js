import { describe, expect, it } from 'vitest';
import { groupGamesByAlphabet, stockedGamesOrAll } from '../lib/gameGroups';

describe('all games alphabetical grouping', () => {
  it('keeps titles outside A-Z visible in the fallback section', () => {
    const grouped = groupGamesByAlphabet([
      { id: 1, name: 'Valorant' },
      { id: 2, name: 'Élite Dangerous' },
      { id: 3, name: '_Hidden Game' },
      { id: 4, name: '2048' },
    ]);

    expect(grouped.map((group) => group.letter)).toEqual(['#', 'V']);
    expect(grouped[0].games.map((game) => game.id)).toEqual(expect.arrayContaining([2, 3, 4]));
    expect(grouped[0].games).toHaveLength(3);
    expect(grouped.flatMap((group) => group.games).map((game) => game.id)).toHaveLength(4);
  });
});

describe('all games stock filter', () => {
  it('lists only games with active listings', () => {
    const picked = stockedGamesOrAll([
      { id: 1, name: 'Steam', listing_count: 12, category_count: 3 },
      { id: 2, name: 'Arena Breakout', listing_count: 0, category_count: 0 },
      { id: 3, name: 'Star Citizen', listing_count: 0, category_count: 2 },
      { id: 4, name: 'Valorant', category_count: 1 },
    ]);
    expect(picked.map((game) => game.id)).toEqual([1]);
  });

  it('falls back to the full catalog when nothing is stocked yet', () => {
    const games = [
      { id: 1, name: 'A', listing_count: 0 },
      { id: 2, name: 'B', listing_count: 0 },
    ];
    expect(stockedGamesOrAll(games)).toBe(games);
  });
});

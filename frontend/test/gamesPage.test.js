import { describe, expect, it } from 'vitest';
import { groupGamesByAlphabet } from '../lib/gameGroups';

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

/**
 * Default emoji icons for games when no uploaded icon is available.
 * Admin can upload proper icons via Django admin panel.
 */
const GAME_ICONS = {
  'valorant': '🎯',
  'pubg-mobile': '🔫',
  'free-fire': '🔥',
  'mobile-legends': '⚔️',
  'call-of-duty-mobile': '💥',
  'fortnite': '🏗️',
  'gta-5': '🚗',
  'clash-of-clans': '🏰',
  'roblox': '🧱',
  'clash-royale': '👑',
};

export function getGameIcon(slug) {
  return GAME_ICONS[slug] || '🎮';
}

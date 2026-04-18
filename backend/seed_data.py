"""
Seed script to populate initial games, categories, and filters.
Run with: python manage.py shell < seed_data.py
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gamesbazaar.settings')
django.setup()

from core.models import Game, Category, GameCategory, Filter, FilterOption, GameCategoryFilter

# ── Games ────────────────────────────────────────────────────────────────────

games_data = [
    {'name': 'Valorant', 'slug': 'valorant', 'description': 'Riot Games tactical shooter', 'order': 1},
    {'name': 'PUBG Mobile', 'slug': 'pubg-mobile', 'description': 'Battle royale mobile game', 'order': 2},
    {'name': 'Free Fire', 'slug': 'free-fire', 'description': 'Garena battle royale', 'order': 3},
    {'name': 'Mobile Legends', 'slug': 'mobile-legends', 'description': 'MOBA mobile game', 'order': 4},
    {'name': 'Call of Duty Mobile', 'slug': 'call-of-duty-mobile', 'description': 'COD on mobile', 'order': 5},
    {'name': 'Fortnite', 'slug': 'fortnite', 'description': 'Epic Games battle royale', 'order': 6},
    {'name': 'GTA 5', 'slug': 'gta-5', 'description': 'Grand Theft Auto V', 'order': 7},
    {'name': 'Clash of Clans', 'slug': 'clash-of-clans', 'description': 'Supercell strategy game', 'order': 8},
    {'name': 'Roblox', 'slug': 'roblox', 'description': 'Online game platform', 'order': 9},
    {'name': 'Clash Royale', 'slug': 'clash-royale', 'description': 'Supercell card battle game', 'order': 10},
]

for gd in games_data:
    Game.objects.get_or_create(slug=gd['slug'], defaults=gd)

print(f"✓ Created {Game.objects.count()} games")

# ── Categories ───────────────────────────────────────────────────────────────

categories_data = [
    {'name': 'Accounts', 'slug': 'accounts', 'icon': '👤', 'description': 'Buy & sell game accounts'},
    {'name': 'Top-Up', 'slug': 'top-up', 'icon': '💰', 'description': 'In-game currency top-ups'},
    {'name': 'Items', 'slug': 'items', 'icon': '⚔️', 'description': 'In-game items and skins'},
    {'name': 'Boosting', 'slug': 'boosting', 'icon': '🚀', 'description': 'Rank boosting services'},
    {'name': 'Coaching', 'slug': 'coaching', 'icon': '🎓', 'description': 'Pro coaching and training'},
]

for cd in categories_data:
    Category.objects.get_or_create(slug=cd['slug'], defaults=cd)

print(f"✓ Created {Category.objects.count()} categories")

# ── Assign categories to games ──────────────────────────────────────────────

assignments = {
    'valorant': ['accounts', 'top-up', 'items', 'boosting', 'coaching'],
    'pubg-mobile': ['accounts', 'top-up', 'items'],
    'free-fire': ['accounts', 'top-up', 'items'],
    'mobile-legends': ['accounts', 'top-up', 'boosting'],
    'call-of-duty-mobile': ['accounts', 'top-up', 'items'],
    'fortnite': ['accounts', 'items'],
    'gta-5': ['accounts', 'items'],
    'clash-of-clans': ['accounts'],
    'roblox': ['accounts', 'items'],
    'clash-royale': ['accounts', 'top-up'],
}

for game_slug, cat_slugs in assignments.items():
    game = Game.objects.get(slug=game_slug)
    for i, cat_slug in enumerate(cat_slugs):
        category = Category.objects.get(slug=cat_slug)
        GameCategory.objects.get_or_create(game=game, category=category, defaults={'order': i})

print(f"✓ Created {GameCategory.objects.count()} game-category assignments")

# ── Filters ──────────────────────────────────────────────────────────────────

filters_data = [
    {
        'name': 'Region',
        'filter_type': 'dropdown',
        'options': [
            ('Asia', 'asia'),
            ('Europe', 'europe'),
            ('North America', 'na'),
            ('Middle East', 'me'),
        ]
    },
    {
        'name': 'Rank',
        'filter_type': 'button',
        'options': [
            ('Iron', 'iron'),
            ('Bronze', 'bronze'),
            ('Silver', 'silver'),
            ('Gold', 'gold'),
            ('Platinum', 'platinum'),
            ('Diamond', 'diamond'),
            ('Immortal', 'immortal'),
            ('Radiant', 'radiant'),
        ]
    },
    {
        'name': 'Platform',
        'filter_type': 'button',
        'options': [
            ('PC', 'pc'),
            ('Mobile', 'mobile'),
            ('Console', 'console'),
        ]
    },
    {
        'name': 'Skins Count',
        'filter_type': 'dropdown',
        'options': [
            ('1-10', '1-10'),
            ('11-50', '11-50'),
            ('50+', '50-plus'),
        ]
    },
]

for fd in filters_data:
    filt, created = Filter.objects.get_or_create(name=fd['name'], defaults={'filter_type': fd['filter_type']})
    for i, (label, value) in enumerate(fd['options']):
        FilterOption.objects.get_or_create(filter=filt, value=value, defaults={'label': label, 'order': i})

print(f"✓ Created {Filter.objects.count()} filters with {FilterOption.objects.count()} options")

# ── Assign filters to game-categories ────────────────────────────────────────

# Valorant Accounts → Region, Rank, Skins Count
val_accounts = GameCategory.objects.get(game__slug='valorant', category__slug='accounts')
for i, fname in enumerate(['Region', 'Rank', 'Skins Count']):
    f = Filter.objects.get(name=fname)
    GameCategoryFilter.objects.get_or_create(game_category=val_accounts, filter=f, defaults={'order': i})

# Valorant Boosting → Rank
val_boosting = GameCategory.objects.get(game__slug='valorant', category__slug='boosting')
f = Filter.objects.get(name='Rank')
GameCategoryFilter.objects.get_or_create(game_category=val_boosting, filter=f, defaults={'order': 0})

# PUBG Mobile Accounts → Region, Platform
pubg_accounts = GameCategory.objects.get(game__slug='pubg-mobile', category__slug='accounts')
for i, fname in enumerate(['Region', 'Platform']):
    f = Filter.objects.get(name=fname)
    GameCategoryFilter.objects.get_or_create(game_category=pubg_accounts, filter=f, defaults={'order': i})

print(f"✓ Created {GameCategoryFilter.objects.count()} filter assignments")
print("\n✅ Seed data complete!")

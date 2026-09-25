from django.db import migrations, models


# Home "Popular" panels, pinned in this order (Shayan 2026-09-25). Games not
# listed here fill the remaining slots by stock, as before. Rentals is left
# unpinned on purpose.
POPULAR_ORDER = {
    'accounts': [
        'gta-5',
        'ea-sports-fc-27',
        'cricket-26-the-official-game-of-the-ashes',
        'ea-fc-26',
    ],
    'keys': [
        'steam',
        'gta-5',
        'red-dead-redemption-2',
        'minecraft',
    ],
    'gift-cards': [
        'playstation',
        'steam',
        'valorant',
        'xbox',
        'roblox',
        'discord',
        'razer-gold',
        'pubg-mobile',
    ],
}


def pin_popular_order(apps, schema_editor):
    GameCategory = apps.get_model('core', 'GameCategory')
    for category_slug, game_slugs in POPULAR_ORDER.items():
        for rank, game_slug in enumerate(game_slugs, start=1):
            GameCategory.objects.filter(
                category__slug=category_slug, game__slug=game_slug,
            ).update(popular_rank=rank)


def restore_featured(apps, schema_editor):
    GameCategory = apps.get_model('core', 'GameCategory')
    GameCategory.objects.filter(popular_rank__isnull=False).update(featured=True)


class Migration(migrations.Migration):
    """Home Popular panels: the on/off "featured" pin becomes a position
    (1 = first) so Shayan controls the exact order, not just which games
    lead the panel."""

    dependencies = [
        ('core', '0084_withdraw_amount_min_1'),
    ]

    operations = [
        migrations.AddField(
            model_name='gamecategory',
            name='popular_rank',
            field=models.PositiveSmallIntegerField(blank=True, help_text='Pin this game to its category\'s "Popular" panel on the home page at this position (1 = first). Blank = not pinned; the panel fills its remaining slots by stock.', null=True, verbose_name='Popular position'),
        ),
        migrations.RunPython(pin_popular_order, restore_featured),
        migrations.RemoveField(
            model_name='gamecategory',
            name='featured',
        ),
    ]

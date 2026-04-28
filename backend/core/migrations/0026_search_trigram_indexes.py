import django.contrib.postgres.indexes
import django.contrib.postgres.operations
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_wallet_balance_non_negative'),
    ]

    operations = [
        django.contrib.postgres.operations.TrigramExtension(),
        migrations.AddIndex(
            model_name='game',
            index=django.contrib.postgres.indexes.GinIndex(
                fields=['name'],
                name='game_name_trgm_idx',
                opclasses=['gin_trgm_ops'],
            ),
        ),
        migrations.AddIndex(
            model_name='game',
            index=django.contrib.postgres.indexes.GinIndex(
                fields=['search_keywords'],
                name='game_search_keywords_trgm_idx',
                opclasses=['gin_trgm_ops'],
            ),
        ),
        migrations.AddIndex(
            model_name='category',
            index=django.contrib.postgres.indexes.GinIndex(
                fields=['name'],
                name='category_name_trgm_idx',
                opclasses=['gin_trgm_ops'],
            ),
        ),
        migrations.AddIndex(
            model_name='listing',
            index=django.contrib.postgres.indexes.GinIndex(
                fields=['title'],
                name='listing_title_trgm_idx',
                opclasses=['gin_trgm_ops'],
            ),
        ),
    ]

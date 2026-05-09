from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0036_order_delivered_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='buyer_protection_enabled',
            field=models.BooleanField(
                default=False,
                help_text='Hold seller payouts for 14 days after order completion in this category.',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='buyer_protection_enabled',
            field=models.BooleanField(
                default=False,
                help_text='Snapshot of whether this order uses the 14-day buyer protection payout hold.',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='seller_payout_available_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When held seller funds become eligible for release.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='seller_payout_released_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When seller funds were credited to the available wallet balance.',
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name='order',
            index=models.Index(
                fields=['status', 'seller_payout_available_at'],
                name='order_payout_due_idx',
            ),
        ),
    ]

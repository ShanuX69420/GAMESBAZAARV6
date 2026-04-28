from django.db import migrations, models


def backfill_order_delivery_snapshots(apps, schema_editor):
    Order = apps.get_model('core', 'Order')

    for order in Order.objects.select_related('listing').iterator():
        listing = order.listing
        if not listing:
            continue
        updates = {}
        if listing.is_auto_delivery:
            updates['was_auto_delivery'] = True
        if listing.delivery_instructions:
            updates['delivery_instructions_snapshot'] = listing.delivery_instructions
        if updates:
            Order.objects.filter(pk=order.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_harden_identity_and_topup_uniqueness'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='was_auto_delivery',
            field=models.BooleanField(
                default=False,
                help_text='Snapshot of whether this order was fulfilled by automated delivery.',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_instructions_snapshot',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Seller instructions captured at purchase time.',
            ),
        ),
        migrations.RunPython(backfill_order_delivery_snapshots, migrations.RunPython.noop),
    ]

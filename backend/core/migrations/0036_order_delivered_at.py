from django.db import migrations, models


def backfill_delivered_at(apps, schema_editor):
    Order = apps.get_model('core', 'Order')
    Order.objects.filter(
        status='delivered',
        delivered_at__isnull=True,
    ).update(delivered_at=models.F('updated_at'))


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0035_order_order_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='delivered_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When the order entered delivered status.',
                null=True,
            ),
        ),
        migrations.RunPython(backfill_delivered_at, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='order',
            index=models.Index(
                fields=['status', 'delivered_at'],
                name='order_status_deliv_idx',
            ),
        ),
    ]

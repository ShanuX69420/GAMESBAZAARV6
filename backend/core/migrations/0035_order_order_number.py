import secrets

from django.db import migrations, models


ORDER_NUMBER_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'


def generate_order_number():
    token = ''.join(secrets.choice(ORDER_NUMBER_ALPHABET) for _ in range(12))
    return f'GB-{token[:4]}-{token[4:8]}-{token[8:]}'


def backfill_order_numbers(apps, schema_editor):
    Order = apps.get_model('core', 'Order')
    used = set(
        Order.objects.exclude(order_number__isnull=True)
        .exclude(order_number='')
        .values_list('order_number', flat=True)
    )
    for order in Order.objects.filter(models.Q(order_number__isnull=True) | models.Q(order_number='')).iterator():
        order_number = generate_order_number()
        while order_number in used or Order.objects.filter(order_number=order_number).exists():
            order_number = generate_order_number()
        used.add(order_number)
        order.order_number = order_number
        order.save(update_fields=['order_number'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0034_add_filter_admin_label'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='order_number',
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=17,
                null=True,
            ),
        ),
        migrations.RunPython(backfill_order_numbers, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='order',
            name='order_number',
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=17,
                unique=True,
            ),
        ),
    ]

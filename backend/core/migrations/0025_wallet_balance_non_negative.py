from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_order_auto_delivery_snapshots'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='wallet',
            constraint=models.CheckConstraint(
                check=models.Q(balance__gte=Decimal('0.00')),
                name='wallet_balance_non_negative',
            ),
        ),
    ]

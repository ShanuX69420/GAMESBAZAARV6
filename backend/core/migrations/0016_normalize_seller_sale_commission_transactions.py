from django.db import migrations


def normalize_sale_commission_transactions(apps, schema_editor):
    Order = apps.get_model('core', 'Order')
    WalletTransaction = apps.get_model('core', 'WalletTransaction')

    orders = Order.objects.filter(commission_amount__gt=0).only(
        'id',
        'seller_id',
        'total_amount',
        'seller_amount',
        'commission_amount',
    )
    for order in orders.iterator():
        reference_id = f'order_{order.pk}'
        sale_tx = WalletTransaction.objects.filter(
            wallet__user_id=order.seller_id,
            transaction_type='sale',
            reference_id=reference_id,
        ).first()
        if not sale_tx or sale_tx.amount != order.seller_amount:
            continue

        commission_tx = WalletTransaction.objects.filter(
            wallet_id=sale_tx.wallet_id,
            transaction_type='commission',
            reference_id=reference_id,
            amount=order.commission_amount,
        ).first()
        if not commission_tx or commission_tx.balance_after != sale_tx.balance_after:
            continue

        sale_tx.amount = order.total_amount
        sale_tx.balance_after = sale_tx.balance_after + order.commission_amount
        sale_tx.save(update_fields=['amount', 'balance_after'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_alter_topuprequest_amount_and_more'),
    ]

    operations = [
        migrations.RunPython(normalize_sale_commission_transactions, migrations.RunPython.noop),
    ]

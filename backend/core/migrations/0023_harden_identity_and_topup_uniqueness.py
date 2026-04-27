from django.db import migrations, models
from django.db.models.functions import Lower, Trim


def normalize_topup_references(apps, schema_editor):
    TopUpRequest = apps.get_model('core', 'TopUpRequest')
    updates = []
    for topup in TopUpRequest.objects.all().only('pk', 'payment_method', 'transaction_id'):
        payment_method = (topup.payment_method or '').strip()
        transaction_id = (topup.transaction_id or '').strip()
        if (
            payment_method != (topup.payment_method or '') or
            transaction_id != (topup.transaction_id or '')
        ):
            topup.payment_method = payment_method
            topup.transaction_id = transaction_id
            updates.append(topup)

    if updates:
        TopUpRequest.objects.bulk_update(updates, ['payment_method', 'transaction_id'])


def normalize_user_emails(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    updates = []
    for user in User.objects.all().only('pk', 'email'):
        email = (user.email or '').strip()
        if email != (user.email or ''):
            user.email = email
            updates.append(user)

    if updates:
        User.objects.bulk_update(updates, ['email'])


def ensure_no_duplicate_active_topup_references(apps, schema_editor):
    TopUpRequest = apps.get_model('core', 'TopUpRequest')
    seen = {}
    duplicates = []
    qs = TopUpRequest.objects.filter(status__in=['pending', 'approved']).exclude(
        transaction_id='',
    )
    for topup in qs.only('pk', 'payment_method', 'transaction_id'):
        key = (
            (topup.payment_method or '').strip().casefold(),
            (topup.transaction_id or '').strip().casefold(),
        )
        if key in seen:
            duplicates.append((seen[key], topup.pk, key))
        else:
            seen[key] = topup.pk

    if duplicates:
        sample = ', '.join(
            f'{first}/{second}:{method}:{transaction_id}'
            for first, second, (method, transaction_id) in duplicates[:5]
        )
        raise RuntimeError(
            'Duplicate active top-up transaction references must be resolved '
            f'before migrating: {sample}'
        )


def ensure_no_duplicate_user_emails(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    seen = {}
    duplicates = []
    for user in User.objects.exclude(email='').only('pk', 'email'):
        key = (user.email or '').strip().casefold()
        if not key:
            continue
        if key in seen:
            duplicates.append((seen[key], user.pk, key))
        else:
            seen[key] = user.pk

    if duplicates:
        sample = ', '.join(
            f'{first}/{second}:{email}'
            for first, second, email in duplicates[:5]
        )
        raise RuntimeError(
            f'Duplicate user emails must be resolved before migrating: {sample}'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_add_username_changed_at'),
    ]

    operations = [
        migrations.RunPython(normalize_topup_references, migrations.RunPython.noop),
        migrations.RunPython(normalize_user_emails, migrations.RunPython.noop),
        migrations.RunPython(
            ensure_no_duplicate_active_topup_references,
            migrations.RunPython.noop,
        ),
        migrations.RunPython(ensure_no_duplicate_user_emails, migrations.RunPython.noop),
        migrations.RunSQL(
            sql=(
                'CREATE UNIQUE INDEX IF NOT EXISTS auth_user_email_ci_uniq '
                'ON auth_user (LOWER(TRIM(email))) '
                "WHERE TRIM(email) <> '';"
            ),
            reverse_sql='DROP INDEX IF EXISTS auth_user_email_ci_uniq;',
        ),
        migrations.AddConstraint(
            model_name='topuprequest',
            constraint=models.UniqueConstraint(
                Lower(Trim('payment_method')),
                Lower(Trim('transaction_id')),
                condition=models.Q(status__in=['pending', 'approved']) &
                ~models.Q(transaction_id=''),
                name='uniq_active_topup_method_txid_ci',
            ),
        ),
    ]

from django.db import migrations


class Migration(migrations.Migration):
    """SteamOfflineAccount → OfflineAccount: offline activation now covers
    Ubisoft and EA accounts too, not just Steam. Pure rename (the table was
    empty on prod when this shipped); the platform/guard_email fields arrive
    in the next auto-generated migration."""

    dependencies = [
        ('core', '0065_order_guard_code_issued_at'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='SteamOfflineAccount',
            new_name='OfflineAccount',
        ),
    ]

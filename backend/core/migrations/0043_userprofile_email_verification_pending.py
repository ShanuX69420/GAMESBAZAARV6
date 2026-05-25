from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0042_message_listing_reference_snapshot'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='email_verification_pending',
            field=models.BooleanField(
                default=False,
                help_text='Whether password registration is awaiting email verification.',
            ),
        ),
    ]

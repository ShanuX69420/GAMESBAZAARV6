from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0041_message_referenced_listing'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='referenced_listing_title',
            field=models.CharField(blank=True, default='', max_length=300),
        ),
        migrations.AddField(
            model_name='message',
            name='referenced_listing_price',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
    ]

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0040_add_has_accepted_terms'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='referenced_listing',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='chat_messages',
                to='core.listing',
            ),
        ),
    ]

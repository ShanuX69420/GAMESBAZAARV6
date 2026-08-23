"""Mint review-link tokens for WhatsApp sales completed before the feature
existed, so those buyers can still be sent a review link."""

import secrets

from django.db import migrations


def backfill_tokens(apps, schema_editor):
    WhatsAppCheckout = apps.get_model('core', 'WhatsAppCheckout')
    completed = WhatsAppCheckout.objects.filter(
        status='completed', review_token__isnull=True,
    )
    for checkout in completed:
        token = secrets.token_urlsafe(24)
        while WhatsAppCheckout.objects.filter(review_token=token).exists():
            token = secrets.token_urlsafe(24)
        checkout.review_token = token
        checkout.save(update_fields=['review_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0075_review_whatsapp_checkout_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_tokens, migrations.RunPython.noop),
    ]

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Listing, Order, WithdrawRequest
from core.services import (
    ENCRYPTED_TEXT_V1_PREFIX,
    decrypt_sensitive_text,
    encrypt_sensitive_text,
)


SENSITIVE_FIELDS = (
    (Listing, 'auto_delivery_data'),
    (Order, 'delivery_note'),
    (WithdrawRequest, 'account_title'),
    (WithdrawRequest, 'account_details'),
)


class Command(BaseCommand):
    help = 'Re-encrypt legacy v1 sensitive text fields with the configured v2 field key.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Count legacy rows without saving changes.',
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'FIELD_ENCRYPTION_PRIMARY_KEY_ID', ''):
            raise CommandError('FIELD_ENCRYPTION_PRIMARY_KEY_ID must be configured.')
        if not getattr(settings, 'FIELD_ENCRYPTION_KEYS', {}):
            raise CommandError('FIELD_ENCRYPTION_KEYS must be configured.')

        dry_run = options['dry_run']
        updated = 0
        skipped = 0

        for model, field_name in SENSITIVE_FIELDS:
            queryset = model.objects.filter(
                **{f'{field_name}__startswith': ENCRYPTED_TEXT_V1_PREFIX}
            ).only('pk', field_name)

            for obj in queryset.iterator():
                current_value = getattr(obj, field_name)
                plain_text = decrypt_sensitive_text(current_value)
                if not plain_text:
                    skipped += 1
                    self.stderr.write(
                        f'Skipping {model.__name__} #{obj.pk}: legacy value could not be decrypted.'
                    )
                    continue

                updated += 1
                if dry_run:
                    continue

                with transaction.atomic():
                    locked_obj = model.objects.select_for_update().get(pk=obj.pk)
                    if getattr(locked_obj, field_name) != current_value:
                        skipped += 1
                        updated -= 1
                        continue
                    setattr(locked_obj, field_name, encrypt_sensitive_text(plain_text))
                    locked_obj.save(update_fields=[field_name])

        action = 'would re-encrypt' if dry_run else 're-encrypted'
        self.stdout.write(
            self.style.SUCCESS(
                f'{action} {updated} legacy sensitive value(s); skipped {skipped}.'
            )
        )

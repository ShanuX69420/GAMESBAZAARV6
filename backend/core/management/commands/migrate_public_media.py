"""Copy public media from the private R2 bucket into the public one.

Avatars, game icons, option icons and review photos used to live in the
private bucket and were handed out as expiring signed URLs. They now belong in
the public bucket (served unsigned on media.gamesbazaar.pk). Stored names are
identical in both buckets, so this is a pure object copy: no data migration.

Idempotent — objects already present in the public bucket are skipped, so run
it before flipping CLOUDFLARE_R2_PUBLIC_MEDIA_ENABLED and once more after, to
catch uploads that landed in between.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import CategoryOption, Game, ReviewImage, UserProfile
from core.storage_backends import (
    PUBLIC_MEDIA_OBJECT_CACHE_CONTROL,
    CloudflareR2PublicStorage,
    CloudflareR2Storage,
    is_cloudflare_r2_name,
    media_content_type,
)

PUBLIC_MEDIA_FIELDS = (
    (UserProfile, 'avatar'),
    (Game, 'icon'),
    (CategoryOption, 'icon'),
    (ReviewImage, 'image'),
)


def referenced_names():
    """Every stored file name the public media fields point at, de-duplicated."""
    seen = set()
    for model, field in PUBLIC_MEDIA_FIELDS:
        queryset = (
            model.objects
            .exclude(**{field: ''})
            .exclude(**{f'{field}__isnull': True})
            .values_list(field, flat=True)
        )
        for name in queryset.iterator():
            name = str(name or '')
            if name and name not in seen:
                seen.add(name)
                yield name


class Command(BaseCommand):
    help = (
        'Copy avatars, game/option icons and review photos from the private R2 '
        'bucket into the public one (idempotent; safe to re-run).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be copied without touching the buckets.',
        )

    def handle(self, *args, **options):
        if not settings.CLOUDFLARE_R2_ENABLED:
            raise CommandError('CLOUDFLARE_R2_ENABLED is off; nothing to copy from.')
        if not settings.CLOUDFLARE_R2_PUBLIC_BUCKET_NAME or not settings.CLOUDFLARE_R2_PUBLIC_MEDIA_HOST:
            raise CommandError(
                'Set CLOUDFLARE_R2_PUBLIC_BUCKET_NAME and CLOUDFLARE_R2_PUBLIC_MEDIA_HOST first '
                '(CLOUDFLARE_R2_PUBLIC_MEDIA_ENABLED may stay off for the first run).'
            )

        dry_run = options['dry_run']
        private = CloudflareR2Storage()
        public = CloudflareR2PublicStorage()
        client = public.connection.meta.client

        copied = already = missing = local = failed = 0
        for name in referenced_names():
            if not is_cloudflare_r2_name(name):
                # Legacy file on local disk: nginx serves /media/ directly,
                # nothing to copy.
                local += 1
                continue
            if public.exists(name):
                already += 1
                continue
            if not private.exists(name):
                missing += 1
                self.stderr.write(f'Missing in private bucket, skipped: {name}')
                continue
            if dry_run:
                copied += 1
                continue
            try:
                client.copy_object(
                    Bucket=public.bucket_name,
                    Key=name,
                    CopySource={'Bucket': private.bucket_name, 'Key': name},
                    MetadataDirective='REPLACE',
                    ContentType=media_content_type(name) or 'application/octet-stream',
                    CacheControl=PUBLIC_MEDIA_OBJECT_CACHE_CONTROL,
                )
                copied += 1
            except Exception as exc:  # noqa: BLE001 - report and keep going
                failed += 1
                self.stderr.write(f'Failed to copy {name}: {exc}')

        verb = 'Would copy' if dry_run else 'Copied'
        summary = (
            f'{verb} {copied} object(s); {already} already public; '
            f'{local} on local disk; {missing} missing from the private bucket; '
            f'{failed} failed.'
        )
        style = self.style.WARNING if dry_run or failed else self.style.SUCCESS
        self.stdout.write(style(summary))
        if failed:
            raise CommandError(f'{failed} object(s) failed to copy.')

from pathlib import PurePosixPath

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from core.models import Game
from core.services import IMAGE_OPTIMIZE_PRESETS, optimize_uploaded_image
from core.storage_backends import CLOUDFLARE_R2_NAME_PREFIX, media_content_type


GAME_ICON_PRESET = IMAGE_OPTIMIZE_PRESETS['game_icon']
GAME_ICON_MAX_SIZE = GAME_ICON_PRESET['max_size']


def icon_filename(name):
    normalized = str(name or '').replace('\\', '/').lstrip('/')
    if normalized.startswith(CLOUDFLARE_R2_NAME_PREFIX):
        normalized = normalized[len(CLOUDFLARE_R2_NAME_PREFIX):]
    return PurePosixPath(normalized).name or 'game-icon'


def inspect_icon(file_field):
    file_field.open('rb')
    try:
        with Image.open(file_field) as image:
            return {
                'format': image.format,
                'width': image.width,
                'height': image.height,
                'bytes': file_field.size,
            }
    finally:
        file_field.close()


def upload_from_icon(file_field):
    filename = icon_filename(file_field.name)
    file_field.open('rb')
    try:
        content = file_field.read()
    finally:
        file_field.close()

    return SimpleUploadedFile(
        filename,
        content,
        content_type=media_content_type(filename) or 'application/octet-stream',
    )


def needs_optimization(metadata, name, force=False):
    if force:
        return True
    return (
        metadata['format'] != 'WEBP' or
        max(metadata['width'], metadata['height']) > GAME_ICON_MAX_SIZE or
        not str(name or '').lower().endswith('.webp')
    )


class Command(BaseCommand):
    help = 'Optimize existing game icons to small WebP files.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Maximum number of icons to optimize in this run.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Count icons that need optimization without saving changes.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Reprocess every icon, including already optimized WebP icons.',
        )
        parser.add_argument(
            '--delete-originals',
            action='store_true',
            help='Delete the old source file after a successful rewrite.',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size must be at least 1.')

        dry_run = options['dry_run']
        force = options['force']
        delete_originals = options['delete_originals']
        optimized = 0
        would_optimize = 0
        skipped = 0
        failed = 0
        deleted = 0

        queryset = (
            Game.objects
            .exclude(icon='')
            .exclude(icon__isnull=True)
            .only('id', 'name', 'icon', 'updated_at')
            .order_by('id')
        )

        for game in queryset.iterator():
            old_name = game.icon.name
            old_storage = game.icon.storage

            try:
                metadata = inspect_icon(game.icon)
            except Exception as exc:
                failed += 1
                self.stderr.write(f'Skipping Game #{game.pk} ({game.name}): cannot read icon: {exc}')
                continue

            if not needs_optimization(metadata, old_name, force=force):
                skipped += 1
                continue

            if optimized >= batch_size:
                break
            would_optimize += 1
            if dry_run:
                continue

            try:
                source_upload = upload_from_icon(game.icon)
                optimized_upload = optimize_uploaded_image(source_upload, preset='game_icon')
                if optimized_upload is source_upload:
                    raise CommandError('optimization returned the original file')

                target_name = icon_filename(optimized_upload.name)
                game.icon.save(target_name, optimized_upload, save=False)
                game.save(update_fields=['icon', 'updated_at'])
                optimized += 1

                if delete_originals and old_name and old_name != game.icon.name:
                    old_storage.delete(old_name)
                    deleted += 1
            except Exception as exc:
                failed += 1
                self.stderr.write(f'Failed Game #{game.pk} ({game.name}): {exc}')

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'Would optimize {would_optimize} game icon(s); '
                    f'{skipped} already optimized; {failed} failed.'
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f'Optimized {optimized} game icon(s); '
                f'{skipped} already optimized; {failed} failed; '
                f'deleted {deleted} original file(s).'
            )
        )

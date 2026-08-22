from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Listing, UserProfile


class Command(BaseCommand):
    """Retire a seller: deactivate their listings and revoke seller status.

    Part of the 2026-08 shop conversion — the marketplace is closed to
    third-party sellers; the house account is the only seller.
    """

    help = "Deactivate all of a seller's active listings and revoke their seller status."

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without writing.')

    def handle(self, *args, **options):
        username = options['username']
        try:
            profile = UserProfile.objects.select_related('user').get(user__username=username)
        except UserProfile.DoesNotExist:
            raise CommandError(f'No user named {username!r}.')

        listings = Listing.objects.filter(seller=profile.user, status='active')
        count = listings.count()

        if options['dry_run']:
            self.stdout.write(
                f'Would deactivate {count} active listing(s) and revoke seller '
                f'status (currently {profile.seller_status!r}).'
            )
            return

        with transaction.atomic():
            # .update() skips auto_now, so stamp updated_at ourselves.
            listings.update(status='inactive', updated_at=timezone.now())
            profile.seller_status = 'none'
            profile.save(update_fields=['seller_status'])

        self.stdout.write(self.style.SUCCESS(
            f'{username}: {count} listing(s) deactivated, seller status revoked.'
        ))

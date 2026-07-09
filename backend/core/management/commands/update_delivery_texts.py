from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from core.models import Listing

# Old seeded-template delivery phrases -> current wording. Exact substrings,
# applied to description and delivery_instructions. Listed with both the
# en-dash form the templates use and a plain-hyphen fallback.
REPLACEMENTS = [
    ('Average delivery: 10 min – 2 hours after purchase',
     'Average delivery: 10–15 minutes after purchase'),
    ('Average delivery: 10 min - 2 hours after purchase',
     'Average delivery: 10-15 minutes after purchase'),
    ('within 1–2 hours', 'within 10–15 minutes'),
    ('within 1-2 hours', 'within 10-15 minutes'),
]


class Command(BaseCommand):
    help = (
        'Rewrite outdated delivery-time phrases inside listing descriptions '
        'and delivery instructions (old "10 min - 2 hours" / "within 1-2 '
        'hours" template wording -> "10-15 minutes").'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without saving anything.')

    def handle(self, *args, **options):
        match_any = Q()
        for old, _ in REPLACEMENTS:
            match_any |= Q(description__contains=old)
            match_any |= Q(delivery_instructions__contains=old)

        hits = {old: 0 for old, _ in REPLACEMENTS}
        changed = []
        for listing in Listing.objects.filter(match_any).iterator():
            for old, new in REPLACEMENTS:
                count = listing.description.count(old) + listing.delivery_instructions.count(old)
                if count:
                    hits[old] += count
                    listing.description = listing.description.replace(old, new)
                    listing.delivery_instructions = listing.delivery_instructions.replace(old, new)
            changed.append(listing)

        for old, count in hits.items():
            if count:
                self.stdout.write(f'  {count:>6}  occurrences of "{old}"')

        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(
                f'[DRY RUN] Would have updated {len(changed)} listings.'
            ))
            return

        now = timezone.now()
        for listing in changed:
            listing.updated_at = now
        Listing.objects.bulk_update(
            changed, ['description', 'delivery_instructions', 'updated_at'],
            batch_size=500,
        )
        self.stdout.write(self.style.SUCCESS(f'Updated {len(changed)} listings.'))

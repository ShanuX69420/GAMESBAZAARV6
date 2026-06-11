import json
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import GameCategory, Listing
from core.serializers import CreateListingSerializer

# Mirrors the create-listing form dropdown; the serializer itself only
# rejects 'Instant' for manual listings, so enforce the rest here to keep
# bulk-imported data consistent with UI-created listings.
MANUAL_DELIVERY_TIMES = ['1-2 Hours', '2-6 Hours', '6-12 Hours', '12-24 Hours', '1-3 Days']

TRUTHY = {'yes', 'y', 'true', '1', 'instant', 'auto'}
FALSY = {'', 'no', 'n', 'false', '0', 'manual', 'none'}


def _norm(value):
    return str(value or '').strip()


def _norm_key(value):
    return _norm(value).casefold()


class RowError(Exception):
    pass


class Command(BaseCommand):
    help = (
        'Bulk-create listings from a JSON rows file (produced from the '
        'bulk-listing spreadsheet). Dry-run by default: validates every row '
        'through CreateListingSerializer and reports problems by row number. '
        'Pass --apply to create the listings (all rows must be valid).'
    )

    def add_arguments(self, parser):
        parser.add_argument('rows_file', help='Path to the JSON rows file.')
        parser.add_argument('--seller', required=True,
                            help='Username of the seller account that will own the listings.')
        parser.add_argument('--apply', action='store_true',
                            help='Actually create the listings. Without this, validate only.')
        parser.add_argument('--allow-duplicates', action='store_true',
                            help='Allow titles that already exist as active listings '
                                 'in the same game/category for this seller.')

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            seller = User.objects.get(username=options['seller'])
        except User.DoesNotExist:
            raise CommandError(f"Seller '{options['seller']}' not found.")

        try:
            with open(options['rows_file'], encoding='utf-8') as fh:
                rows = json.load(fh)
        except (OSError, ValueError) as exc:
            raise CommandError(f'Could not read rows file: {exc}')
        if not isinstance(rows, list) or not rows:
            raise CommandError('Rows file must be a non-empty JSON list.')

        self._gc_cache = {}
        for gc in (GameCategory.objects.filter(game__is_active=True)
                   .select_related('game', 'category')
                   .prefetch_related('options', 'assigned_filters__filter__options')):
            for game_key in (_norm_key(gc.game.name), _norm_key(gc.game.slug)):
                for cat_key in (_norm_key(gc.category.name), _norm_key(gc.category.slug)):
                    self._gc_cache[(game_key, cat_key)] = gc

        errors = []
        prepared = []
        seen_titles = set()

        for i, row in enumerate(rows):
            row_no = row.get('row', i + 2)  # default: spreadsheet data starts at row 2
            try:
                payload, gc = self._build_payload(row)

                dup_key = (gc.id, _norm_key(payload.get('title') or row.get('option')))
                if dup_key in seen_titles:
                    raise RowError('Duplicate of an earlier row in this file '
                                   '(same game, category and title).')
                seen_titles.add(dup_key)

                if not options['allow_duplicates'] and payload.get('title'):
                    if Listing.objects.filter(
                        seller=seller, game_category=gc, status='active',
                        title__iexact=payload['title'],
                    ).exists():
                        raise RowError('An active listing with this title already exists '
                                       'in this game/category (use --allow-duplicates to override).')

                serializer = CreateListingSerializer(
                    data=payload,
                    context={'request': SimpleNamespace(user=seller)},
                )
                if not serializer.is_valid():
                    raise RowError(json.dumps(serializer.errors, ensure_ascii=False))
                prepared.append((row_no, serializer, payload))
            except RowError as exc:
                errors.append((row_no, str(exc)))

        for row_no, message in errors:
            self.stdout.write(self.style.ERROR(f'row {row_no}: {message}'))
        self.stdout.write(
            f'\n{len(prepared)} of {len(rows)} rows valid, {len(errors)} with errors.'
        )

        if errors:
            raise CommandError('Fix the rows above and re-run. Nothing was created.')

        if not options['apply']:
            for row_no, serializer, payload in prepared[:10]:
                v = serializer.validated_data
                gc = v['game_category']
                self.stdout.write(
                    f"row {row_no}: OK - \"{v.get('title') or v['option'].name}\" "
                    f"PKR {v['price']} ({gc.game.name} / {gc.category.name})"
                )
            if len(prepared) > 10:
                self.stdout.write(f'... and {len(prepared) - 10} more.')
            self.stdout.write(self.style.WARNING(
                '\nDry run only — re-run with --apply to create these listings.'
            ))
            return

        with transaction.atomic():
            for row_no, serializer, payload in prepared:
                serializer.save()
        self.stdout.write(self.style.SUCCESS(
            f'Created {len(prepared)} listings for {seller.username}.'
        ))

    def _build_payload(self, row):
        game = _norm(row.get('game'))
        category = _norm(row.get('category'))
        if not game or not category:
            raise RowError('Both "game" and "category" are required.')
        gc = self._gc_cache.get((_norm_key(game), _norm_key(category)))
        if gc is None:
            raise RowError(f'Unknown game/category: "{game}" / "{category}". '
                           'Check the Reference sheet for exact names.')

        instant_raw = _norm_key(row.get('instant_delivery'))
        if instant_raw in TRUTHY:
            is_auto = True
        elif instant_raw in FALSY:
            is_auto = False
        else:
            raise RowError(f'instant_delivery must be yes or no, got "{instant_raw}".')

        codes = str(row.get('delivery_codes') or '')
        if is_auto and not codes.strip():
            raise RowError('instant_delivery is yes but delivery_codes is empty — '
                           'put one code/account per line.')
        if not is_auto and codes.strip():
            raise RowError('delivery_codes is filled but instant_delivery is no — '
                           'set it to yes, or clear the codes.')

        delivery_time = _norm(row.get('delivery_time'))
        if is_auto:
            delivery_time = 'Instant'
        else:
            delivery_time = delivery_time or '1-2 Hours'
            if delivery_time not in MANUAL_DELIVERY_TIMES:
                raise RowError(f'delivery_time must be one of {MANUAL_DELIVERY_TIMES}, '
                               f'got "{delivery_time}".')

        option_name = _norm(row.get('option'))
        option_id = None
        if option_name:
            matches = [o for o in gc.options.all()
                       if _norm_key(o.name) == _norm_key(option_name)]
            if not matches:
                valid = ', '.join(o.name for o in gc.options.all()) or '(none)'
                raise RowError(f'Unknown option "{option_name}". Valid options: {valid}.')
            option_id = matches[0].id

        quantity = _norm(row.get('quantity'))
        if quantity and not is_auto:
            try:
                quantity = int(quantity)
            except ValueError:
                raise RowError(f'quantity must be a whole number or blank, got "{quantity}".')
        else:
            quantity = None  # unlimited, or derived from delivery_codes lines

        return {
            'game_slug': gc.game.slug,
            'category_slug': gc.category.slug,
            'option_id': option_id,
            'title': _norm(row.get('title')),
            'description': str(row.get('description') or '').strip(),
            'price': _norm(row.get('price')),
            'quantity': quantity,
            'delivery_time': delivery_time,
            'is_auto_delivery': is_auto,
            'auto_delivery_data': codes,
            'delivery_instructions': str(row.get('delivery_instructions') or '').strip(),
            'filter_values': self._resolve_filters(row.get('filters'), gc),
        }, gc

    def _resolve_filters(self, raw, gc):
        """Turn 'Rank=Conqueror; Level=70' (or a dict) into {filter_id: value}."""
        pairs = {}
        if isinstance(raw, dict):
            pairs = {_norm(k): _norm(v) for k, v in raw.items()}
        elif _norm(raw):
            for chunk in _norm(raw).replace('\n', ';').split(';'):
                chunk = chunk.strip()
                if not chunk:
                    continue
                if '=' not in chunk:
                    raise RowError(f'Bad filters entry "{chunk}" — use Name=Value; Name=Value.')
                name, _, value = chunk.partition('=')
                pairs[name.strip()] = value.strip()

        assigned = list(gc.assigned_filters.all())
        by_name = {_norm_key(gcf.filter.name): gcf for gcf in assigned}

        filter_values = {}
        for name, value in pairs.items():
            gcf = by_name.get(_norm_key(name))
            if gcf is None:
                valid = ', '.join(g.filter.name for g in assigned) or '(none)'
                raise RowError(f'Filter "{name}" does not exist here. '
                               f'Filters for this category: {valid}.')
            match = next(
                (fo for fo in gcf.filter.options.all()
                 if _norm_key(fo.label) == _norm_key(value) or
                    _norm_key(fo.value) == _norm_key(value)),
                None,
            )
            if match is None:
                valid = ', '.join(fo.label for fo in gcf.filter.options.all())
                raise RowError(f'"{value}" is not a valid {gcf.filter.name}. '
                               f'Allowed: {valid}.')
            filter_values[str(gcf.filter_id)] = match.value
        return filter_values

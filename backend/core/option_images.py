"""Product pictures for tile-based options (gift cards, currency, subscriptions).

One 900x600 WebP per CategoryOption, composed from parts we own or licence:
the brand's white logo (core/data/brand_logos/), a flag from the MIT
flag-icons set rasterised to PNG (core/data/flags/), the option's amount and
currency parsed from its name, and Inter (OFL, core/data/fonts/). Nothing is
copied from the publisher's card art.

Layout is crop-safe on purpose: everything that matters (logo lock-up,
amount, region badge) sits inside the central 600x480 area, so the square
thumbnail Google Images cuts, the 4:3 crop of a Product rich result and the
~1.9:1 crop of a WhatsApp preview all keep the three facts a buyer needs.
Only the corner watermark and the faint background mark may be cropped away.

`generate_option_images` calls `render_option_image`; the admin's own upload
on CategoryOption.image overrides whatever this produces.
"""
import hashlib
import io
import json
import re
from functools import lru_cache
from pathlib import Path

from django.utils.text import slugify
from PIL import Image, ImageDraw, ImageFont

DATA_DIR = Path(__file__).resolve().parent / 'data'
FONT_PATH = DATA_DIR / 'fonts' / 'Inter-Variable.ttf'
FLAG_DIR = DATA_DIR / 'flags'
LOGO_DIR = DATA_DIR / 'brand_logos'
BRANDS_PATH = DATA_DIR / 'option_image_brands.json'
REGIONS_PATH = DATA_DIR / 'option_image_regions.json'

CARD_WIDTH, CARD_HEIGHT = 900, 600
WEBP_QUALITY = 82
WATERMARK = 'gamesbazaar.pk'

# "50 USD (USA)", "1,000 INR (India)", "60 UC", "10 EUR"
OPTION_NAME_RE = re.compile(
    r'^\s*(?P<amount>\d[\d,\.]*)\s*(?P<currency>[A-Z]{2,4})?\s*'
    r'(?:\((?P<region>[^)]+)\))?\s*$'
)


def load_brands():
    with open(BRANDS_PATH, encoding='utf-8') as fh:
        data = json.load(fh)
    return {k: v for k, v in data.items() if not k.startswith('_')}


def load_regions():
    with open(REGIONS_PATH, encoding='utf-8') as fh:
        data = json.load(fh)
    return {k: v for k, v in data.items() if not k.startswith('_')}


def parse_option_name(name):
    """'50 USD (USA)' -> {'amount': '50', 'currency': 'USD', 'region': 'USA'};
    None when the name is not amount-shaped (subscriptions, bundles)."""
    match = OPTION_NAME_RE.match(name or '')
    if not match:
        return None
    amount = match.group('amount').replace(',', '')
    if not re.fullmatch(r'\d+(\.\d+)?', amount):
        return None
    if amount.endswith('.0') or amount.endswith('.00'):
        amount = amount.split('.')[0]
    return {
        'amount': amount,
        'currency': (match.group('currency') or '').upper(),
        'region': (match.group('region') or '').strip(),
    }


def image_filename(brand_slug, parsed, region_name, data):
    """Descriptive name for image search plus a content hash so a regenerated
    design never collides with a copy an edge cache still holds."""
    parts = [brand_slug, region_name or parsed['region'] or 'global',
             parsed['amount'], parsed['currency'].lower()]
    stem = slugify('-'.join(p for p in parts if p)) or 'option'
    digest = hashlib.sha1(data).hexdigest()[:8]
    return f'{stem}-{digest}.webp'


# -- drawing helpers ----------------------------------------------------------

@lru_cache(maxsize=64)
def _font(weight, size):
    font = ImageFont.truetype(str(FONT_PATH), size)
    # Inter's optical-size axis runs 14-32; the display cut suits big text.
    font.set_variation_by_axes([max(14, min(32, size)), weight])
    return font


@lru_cache(maxsize=16)
def _logo(filename):
    return Image.open(LOGO_DIR / filename).convert('RGBA')


@lru_cache(maxsize=128)
def _flag(iso):
    path = FLAG_DIR / f'{iso}.png'
    if not path.exists():
        return None
    return Image.open(path).convert('RGBA')


def _hex(colour):
    colour = colour.lstrip('#')
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


def _gradient(top_left, bottom_right):
    tl, br = _hex(top_left), _hex(bottom_right)
    mid = tuple((a + b) // 2 for a, b in zip(tl, br))
    seed = Image.new('RGB', (2, 2))
    seed.putdata([tl, mid, mid, br])
    return seed.resize((CARD_WIDTH, CARD_HEIGHT), Image.BICUBIC).convert('RGBA')


def _tinted(image, alpha):
    """Copy of an RGBA image with its alpha scaled by `alpha` (0..1)."""
    out = image.copy()
    out.putalpha(out.getchannel('A').point(lambda v: int(v * alpha)))
    return out


def _fit_height(image, height):
    width = max(1, round(image.width * height / image.height))
    return image.resize((width, height), Image.LANCZOS)


def _rounded(image, radius):
    mask = Image.new('L', image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, image.width - 1, image.height - 1],
                                           radius=radius, fill=255)
    out = image.copy()
    out.putalpha(mask)
    return out


def _spaced_width(font, text, spacing):
    return sum(font.getlength(ch) for ch in text) + spacing * (len(text) - 1)


def _draw_spaced(draw, xy, text, font, fill, spacing):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill, anchor='ls')
        x += font.getlength(ch) + spacing


def _amount_font_size(amount_text):
    digits = len(amount_text.replace(',', '').replace('.', ''))
    return {1: 200, 2: 200, 3: 200, 4: 168, 5: 140, 6: 120, 7: 104}.get(digits, 92)


def _format_amount(amount):
    if '.' in amount:
        whole, frac = amount.split('.', 1)
        return f'{int(whole):,}.{frac}'
    return f'{int(amount):,}' if len(amount) >= 5 else amount


# -- the card -----------------------------------------------------------------

def render_option_image(brand, parsed, region=None):
    """Compose one card. `brand` is an entry of option_image_brands.json,
    `parsed` comes from parse_option_name, `region` is the matching entry of
    option_image_regions.json (or None for a text-only badge). Returns WebP
    bytes."""
    white = (255, 255, 255)
    card = _gradient(brand['bg'][0], brand['bg'][1])
    logo = _logo(brand['logo'])

    # Faint brand mark bleeding off the right edge: depth, not information.
    ghost = _tinted(_fit_height(logo, 430), 0.07)
    card.alpha_composite(ghost, (610, 110))

    # A soft diagonal sheen so the flat gradient reads as a card.
    sheen = Image.new('RGBA', card.size, (0, 0, 0, 0))
    ImageDraw.Draw(sheen).polygon([(380, 0), (700, 0), (420, CARD_HEIGHT), (100, CARD_HEIGHT)],
                                  fill=(255, 255, 255, 12))
    card.alpha_composite(sheen)

    layer = Image.new('RGBA', card.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    # Lock-up: logo + two-line wordmark, centred at the top.
    lockup_logo = _fit_height(logo, 84)
    line1, line2 = brand['wordmark']
    f1, f2 = _font(700, 34), _font(500, 24)
    text_w = max(f1.getlength(line1), f2.getlength(line2))
    total_w = lockup_logo.width + 18 + text_w
    x0 = round((CARD_WIDTH - total_w) / 2)
    layer.alpha_composite(lockup_logo, (x0, 62))
    tx = x0 + lockup_logo.width + 18
    draw.text((tx, 72), line1, font=f1, fill=white + (255,), anchor='la')
    draw.text((tx, 116), line2, font=f2, fill=white + (217,), anchor='la')

    # The amount, as large as its digit count allows, with the currency code
    # under it. Both centred so a square crop keeps them.
    amount_text = _format_amount(parsed['amount'])
    fa = _font(800, _amount_font_size(amount_text))
    draw.text((CARD_WIDTH / 2, 372), amount_text, font=fa, fill=white + (255,), anchor='ms')
    if parsed['currency']:
        fc = _font(700, 40)
        cw = _spaced_width(fc, parsed['currency'], 6)
        _draw_spaced(draw, ((CARD_WIDTH - cw) / 2, 446), parsed['currency'], fc,
                     white + (235,), 6)

    # Region badge: flag + name in a translucent pill at the bottom centre.
    region_name = (region or {}).get('name') or parsed['region']
    if region_name:
        flag = _flag(region['iso']) if region and region.get('iso') else None
        fr = _font(700, 30)
        name_w = fr.getlength(region_name)
        flag_w = 56 if flag else 0
        pill_w = 22 + flag_w + (14 if flag else 0) + name_w + 24
        px = round((CARD_WIDTH - pill_w) / 2)
        py = 462
        draw.rounded_rectangle([px, py, px + pill_w, py + 64], radius=32,
                               fill=(255, 255, 255, 36), outline=(255, 255, 255, 64), width=1)
        cx = px + 22
        if flag:
            flag_img = _rounded(flag.resize((56, 42), Image.LANCZOS), 6)
            layer.alpha_composite(flag_img, (cx, py + 11))
            cx += 56 + 14
        draw.text((cx, py + 32), region_name, font=fr, fill=white + (255,), anchor='lm')

    # Watermark in the corner, outside the crop-safe area, so it is the one
    # thing a thumbnail may lose.
    draw.text((850, 570), WATERMARK, font=_font(600, 22), fill=white + (140,), anchor='rs')

    card.alpha_composite(layer)
    buffer = io.BytesIO()
    card.convert('RGB').save(buffer, 'WEBP', quality=WEBP_QUALITY, method=6)
    return buffer.getvalue()

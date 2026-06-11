"""
Seed rich local demo data for browsing the marketplace.

Run from backend:
    python manage.py shell < seed_data.py

The script is idempotent for the records it owns: re-running it updates the
same demo users, filters, game categories, and listing titles instead of
creating another copy each time.
"""

import os
from decimal import Decimal

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gamesbazaar.settings")
django.setup()

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.models import (
    Category,
    CategoryOption,
    Conversation,
    Filter,
    FilterOption,
    Game,
    GameCategory,
    GameCategoryFilter,
    Listing,
    Message,
    UserProfile,
    Wallet,
)


DEMO_PASSWORD = "demo12345"
BASE_LISTINGS_PER_CATEGORY = {
    "accounts": 14,
    "top-up": 10,
    "items": 10,
    "boosting": 8,
    "coaching": 6,
    "gift-cards": 8,
    "currency": 10,
}
LARGE_LISTING_SETS = {
    ("valorant", "accounts"): 72,
    ("pubg-mobile", "top-up"): 56,
    ("roblox", "currency"): 54,
}

# Offer-mode demos: admin-defined options where sellers compete on price.
OFFER_MODE_DEMOS = [
    {
        "game_slug": "pubg-mobile",
        "category_order": 10,
        "category": {
            "name": "UC",
            "slug": "uc",
            "icon": "UC",
            "description": "PUBG Mobile UC top-ups from competing sellers.",
            "commission_rate": Decimal("4.00"),
        },
        "delivery_instructions": (
            "Only your Player ID / UID is required. No password or account login needed.\n\n"
            "How to find your UID: open PUBG Mobile > Profile > copy your Player ID.\n\n"
            "Please double-check your UID before ordering. Completed top-ups cannot be "
            "cancelled or refunded."
        ),
        "options": [
            {"name": "60 UC", "base_price": Decimal("220.00"), "popular": True},
            {"name": "325 UC", "base_price": Decimal("1150.00")},
            {"name": "660 UC", "base_price": Decimal("2300.00")},
            {"name": "1800 UC", "base_price": Decimal("6200.00")},
            {"name": "3850 UC", "base_price": Decimal("13000.00")},
            {"name": "8100 UC", "base_price": Decimal("26500.00")},
        ],
    },
    {
        "game_slug": "free-fire",
        "category_order": 10,
        "category": {
            "name": "Diamonds",
            "slug": "diamonds",
            "icon": "DIA",
            "description": "Free Fire diamond top-ups from competing sellers.",
            "commission_rate": Decimal("4.00"),
        },
        "delivery_instructions": (
            "Send your Free Fire Player ID only. We never need your password.\n\n"
            "Make sure your ID is correct — wrong IDs cannot be refunded after delivery."
        ),
        "options": [
            {"name": "100 Diamonds", "base_price": Decimal("300.00")},
            {"name": "310 Diamonds", "base_price": Decimal("900.00"), "popular": True},
            {"name": "520 Diamonds", "base_price": Decimal("1500.00")},
            {"name": "1060 Diamonds", "base_price": Decimal("3000.00")},
            {"name": "2180 Diamonds", "base_price": Decimal("6000.00")},
            {"name": "5600 Diamonds", "base_price": Decimal("15500.00")},
        ],
    },
]


GAMES = [
    {
        "name": "Valorant",
        "slug": "valorant",
        "description": "Riot Games tactical shooter.",
        "order": 1,
    },
    {
        "name": "PUBG Mobile",
        "slug": "pubg-mobile",
        "description": "Mobile battle royale accounts, UC, and services.",
        "order": 2,
    },
    {
        "name": "Free Fire",
        "slug": "free-fire",
        "description": "Garena battle royale accounts, diamonds, and items.",
        "order": 3,
    },
    {
        "name": "Mobile Legends",
        "slug": "mobile-legends",
        "description": "MOBA accounts, diamonds, boosting, and coaching.",
        "order": 4,
    },
    {
        "name": "Call of Duty Mobile",
        "slug": "call-of-duty-mobile",
        "description": "COD Mobile accounts, CP, and weapon skins.",
        "order": 5,
    },
    {
        "name": "Fortnite",
        "slug": "fortnite",
        "description": "Fortnite accounts, V-Bucks, skins, and bundles.",
        "order": 6,
    },
    {
        "name": "GTA 5",
        "slug": "gta-5",
        "description": "GTA Online accounts, money, and rare unlocks.",
        "order": 7,
    },
    {
        "name": "Clash of Clans",
        "slug": "clash-of-clans",
        "description": "Village accounts, gems, and clan services.",
        "order": 8,
    },
    {
        "name": "Roblox",
        "slug": "roblox",
        "description": "Roblox accounts, Robux, and limited items.",
        "order": 9,
    },
    {
        "name": "Clash Royale",
        "slug": "clash-royale",
        "description": "Arena accounts, gems, cards, and coaching.",
        "order": 10,
    },
    {
        "name": "League of Legends",
        "slug": "league-of-legends",
        "description": "League accounts, RP, skins, boosting, and coaching.",
        "order": 11,
    },
    {
        "name": "Dota 2",
        "slug": "dota-2",
        "description": "Dota accounts, items, rank boosting, and coaching.",
        "order": 12,
    },
    {
        "name": "Counter-Strike 2",
        "slug": "counter-strike-2",
        "description": "CS2 accounts, skins, cases, and coaching.",
        "order": 13,
    },
    {
        "name": "Genshin Impact",
        "slug": "genshin-impact",
        "description": "Genshin accounts, Primogems, and character packs.",
        "order": 14,
    },
    {
        "name": "EA FC",
        "slug": "ea-fc",
        "description": "EA FC coins, accounts, squads, and coaching.",
        "order": 15,
    },
    {
        "name": "Minecraft",
        "slug": "minecraft",
        "description": "Minecraft accounts, gift codes, and server items.",
        "order": 16,
    },
    {
        "name": "Apex Legends",
        "slug": "apex-legends",
        "description": "Apex accounts, coins, heirlooms, and boosting.",
        "order": 17,
    },
    {
        "name": "Overwatch 2",
        "slug": "overwatch-2",
        "description": "Overwatch accounts, coins, skins, and coaching.",
        "order": 18,
    },
]


CATEGORIES = [
    {
        "name": "Accounts",
        "slug": "accounts",
        "icon": "ACCT",
        "description": "Game accounts with ranks, skins, and unlocks.",
        "commission_rate": Decimal("5.00"),
    },
    {
        "name": "Top-Up",
        "slug": "top-up",
        "icon": "TOP",
        "description": "In-game currency top-ups and recharge services.",
        "commission_rate": Decimal("4.00"),
    },
    {
        "name": "Items",
        "slug": "items",
        "icon": "ITEM",
        "description": "Skins, bundles, weapons, cards, and collectibles.",
        "commission_rate": Decimal("6.00"),
    },
    {
        "name": "Boosting",
        "slug": "boosting",
        "icon": "BST",
        "description": "Rank boosting and progression services.",
        "commission_rate": Decimal("8.00"),
    },
    {
        "name": "Coaching",
        "slug": "coaching",
        "icon": "CO",
        "description": "One-on-one coaching and replay reviews.",
        "commission_rate": Decimal("7.00"),
    },
    {
        "name": "Gift Cards",
        "slug": "gift-cards",
        "icon": "GIFT",
        "description": "Wallet codes, platform cards, and redeemable keys.",
        "commission_rate": Decimal("3.50"),
    },
    {
        "name": "Currency",
        "slug": "currency",
        "icon": "CUR",
        "description": "Coins, gems, credits, Robux, RP, and similar currency.",
        "commission_rate": Decimal("4.50"),
    },
]


ASSIGNMENTS = {
    "valorant": ["accounts", "top-up", "items", "boosting", "coaching", "gift-cards"],
    "pubg-mobile": ["accounts", "top-up", "items", "boosting", "currency"],
    "free-fire": ["accounts", "top-up", "items", "boosting", "currency"],
    "mobile-legends": ["accounts", "top-up", "items", "boosting", "coaching", "currency"],
    "call-of-duty-mobile": ["accounts", "top-up", "items", "boosting", "currency"],
    "fortnite": ["accounts", "top-up", "items", "boosting", "gift-cards", "currency"],
    "gta-5": ["accounts", "items", "boosting", "currency"],
    "clash-of-clans": ["accounts", "top-up", "boosting", "currency"],
    "roblox": ["accounts", "items", "gift-cards", "currency"],
    "clash-royale": ["accounts", "top-up", "items", "boosting", "coaching"],
    "league-of-legends": ["accounts", "top-up", "items", "boosting", "coaching", "currency"],
    "dota-2": ["accounts", "items", "boosting", "coaching"],
    "counter-strike-2": ["accounts", "items", "boosting", "coaching"],
    "genshin-impact": ["accounts", "top-up", "items", "currency"],
    "ea-fc": ["accounts", "items", "coaching", "currency"],
    "minecraft": ["accounts", "items", "gift-cards"],
    "apex-legends": ["accounts", "top-up", "items", "boosting", "currency"],
    "overwatch-2": ["accounts", "top-up", "items", "boosting", "coaching", "currency"],
}


FILTERS = [
    (
        "Region",
        "dropdown",
        [
            ("Asia", "asia"),
            ("Pakistan", "pakistan"),
            ("Middle East", "middle-east"),
            ("Europe", "europe"),
            ("North America", "north-america"),
            ("Singapore", "singapore"),
            ("Global", "global"),
        ],
    ),
    (
        "Rank",
        "button",
        [
            ("Unranked", "unranked"),
            ("Bronze", "bronze"),
            ("Silver", "silver"),
            ("Gold", "gold"),
            ("Platinum", "platinum"),
            ("Diamond", "diamond"),
            ("Ascendant", "ascendant"),
            ("Immortal", "immortal"),
            ("Radiant", "radiant"),
            ("Master", "master"),
            ("Grandmaster", "grandmaster"),
            ("Mythic", "mythic"),
            ("Conqueror", "conqueror"),
        ],
    ),
    (
        "Platform",
        "button",
        [
            ("PC", "pc"),
            ("Mobile", "mobile"),
            ("PlayStation", "playstation"),
            ("Xbox", "xbox"),
            ("Switch", "switch"),
            ("Cross Platform", "cross-platform"),
        ],
    ),
    (
        "Delivery Time",
        "dropdown",
        [
            ("Instant", "instant"),
            ("Under 1 Hour", "under-1-hour"),
            ("Same Day", "same-day"),
            ("24 Hours", "24-hours"),
            ("2-3 Days", "2-3-days"),
        ],
    ),
    (
        "Account Level",
        "dropdown",
        [
            ("Starter", "starter"),
            ("Mid Level", "mid-level"),
            ("High Level", "high-level"),
            ("Maxed", "maxed"),
            ("Rare", "rare"),
            ("Stacked", "stacked"),
        ],
    ),
    (
        "Skins Count",
        "dropdown",
        [
            ("1-10", "1-10"),
            ("11-50", "11-50"),
            ("51-100", "51-100"),
            ("100+", "100-plus"),
            ("250+", "250-plus"),
        ],
    ),
    (
        "Server",
        "dropdown",
        [
            ("Asia", "asia"),
            ("Europe", "europe"),
            ("North America", "north-america"),
            ("Middle East", "middle-east"),
            ("Singapore", "singapore"),
            ("Global", "global"),
        ],
    ),
    (
        "Warranty",
        "dropdown",
        [
            ("No Warranty", "none"),
            ("3 Days", "3-days"),
            ("7 Days", "7-days"),
            ("14 Days", "14-days"),
            ("30 Days", "30-days"),
        ],
    ),
    (
        "Item Type",
        "dropdown",
        [
            ("Skins", "skins"),
            ("Bundle", "bundle"),
            ("Weapon", "weapon"),
            ("Cards", "cards"),
            ("Coins", "coins"),
            ("Gems", "gems"),
            ("UC", "uc"),
            ("CP", "cp"),
            ("RP", "rp"),
            ("V-Bucks", "v-bucks"),
            ("Robux", "robux"),
            ("Primogems", "primogems"),
        ],
    ),
    (
        "Language",
        "button",
        [
            ("English", "english"),
            ("Urdu", "urdu"),
            ("Hindi", "hindi"),
            ("Arabic", "arabic"),
        ],
    ),
]


CATEGORY_FILTERS = {
    "accounts": ["Region", "Platform", "Account Level", "Rank", "Skins Count", "Warranty"],
    "top-up": ["Region", "Server", "Delivery Time", "Item Type"],
    "items": ["Region", "Platform", "Item Type", "Delivery Time"],
    "boosting": ["Region", "Platform", "Rank", "Delivery Time"],
    "coaching": ["Region", "Platform", "Rank", "Delivery Time", "Language"],
    "gift-cards": ["Region", "Platform", "Delivery Time", "Warranty"],
    "currency": ["Region", "Server", "Delivery Time", "Item Type"],
}


SELLERS = [
    {
        "username": "seller_ak",
        "email": "seller_ak@example.com",
        "first_name": "Ahmed",
        "last_name": "Khan",
        "wallet": Decimal("15000.00"),
    },
    {
        "username": "seller_pro",
        "email": "seller_pro@example.com",
        "first_name": "Sara",
        "last_name": "Pro",
        "wallet": Decimal("22000.00"),
    },
    {
        "username": "seller_fast",
        "email": "seller_fast@example.com",
        "first_name": "Fast",
        "last_name": "Delivery",
        "wallet": Decimal("18500.00"),
    },
    {
        "username": "seller_boost",
        "email": "seller_boost@example.com",
        "first_name": "Rank",
        "last_name": "Boost",
        "wallet": Decimal("34000.00"),
    },
    {
        "username": "seller_store",
        "email": "seller_store@example.com",
        "first_name": "Game",
        "last_name": "Store",
        "wallet": Decimal("28000.00"),
    },
]

BUYERS = [
    {
        "username": "demo_buyer",
        "email": "buyer@example.com",
        "first_name": "Demo",
        "last_name": "Buyer",
        "wallet": Decimal("250000.00"),
    }
]


def update_fields(obj, defaults):
    changed = []
    for field_name, value in defaults.items():
        if getattr(obj, field_name) != value:
            setattr(obj, field_name, value)
            changed.append(field_name)
    if changed:
        obj.save(update_fields=changed)
    return obj


def upsert_game(data):
    defaults = {
        "name": data["name"],
        "description": data["description"],
        "order": data["order"],
        "is_active": True,
    }
    game, _ = Game.objects.get_or_create(
        slug=data["slug"],
        defaults={**defaults, "slug": data["slug"]},
    )
    return update_fields(game, defaults)


def upsert_category(data):
    defaults = {
        "name": data["name"],
        "description": data["description"],
        "icon": data["icon"],
        "commission_rate": data["commission_rate"],
    }
    category, _ = Category.objects.get_or_create(
        slug=data["slug"],
        defaults={**defaults, "slug": data["slug"]},
    )
    return update_fields(category, defaults)


def upsert_game_category(game, category, order):
    game_category = (
        GameCategory.objects.filter(game=game, category=category).order_by("id").first()
    )
    if not game_category:
        return GameCategory.objects.create(game=game, category=category, order=order)
    return update_fields(game_category, {"order": order})


def upsert_filter(name, filter_type):
    filter_obj = Filter.objects.filter(name=name).order_by("id").first()
    if not filter_obj:
        return Filter.objects.create(name=name, filter_type=filter_type)
    return update_fields(filter_obj, {"filter_type": filter_type})


def upsert_filter_option(filter_obj, label, value, order):
    option = (
        FilterOption.objects.filter(filter=filter_obj, value=value).order_by("id").first()
    )
    defaults = {"label": label, "order": order}
    if not option:
        return FilterOption.objects.create(
            filter=filter_obj,
            label=label,
            value=value,
            order=order,
        )
    return update_fields(option, defaults)


def upsert_game_category_filter(game_category, filter_obj, order):
    assignment = (
        GameCategoryFilter.objects.filter(game_category=game_category, filter=filter_obj)
        .order_by("id")
        .first()
    )
    if not assignment:
        return GameCategoryFilter.objects.create(
            game_category=game_category,
            filter=filter_obj,
            order=order,
        )
    return update_fields(assignment, {"order": order})


def set_wallet_balance(user, balance):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return update_fields(wallet, {"balance": balance})


def upsert_user(data, seller_status):
    User = get_user_model()
    defaults = {
        "email": data["email"],
        "first_name": data["first_name"],
        "last_name": data["last_name"],
        "is_active": True,
    }
    user, _ = User.objects.get_or_create(username=data["username"], defaults=defaults)
    update_fields(user, defaults)
    user.set_password(DEMO_PASSWORD)
    user.save(update_fields=["password"])

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile_defaults = {
        "seller_status": seller_status,
        "seller_application_note": "Seeded local demo seller.",
        "seller_reviewed_at": timezone.now() if seller_status == "approved" else None,
    }
    if seller_status == "none":
        profile_defaults["seller_application_note"] = ""
    update_fields(profile, profile_defaults)
    set_wallet_balance(user, data["wallet"])
    return user


def option_label(option_map, filter_name, index):
    options = option_map[filter_name]
    return options[index % len(options)].label


def option_value(option_map, filter_name, index):
    options = option_map[filter_name]
    return options[index % len(options)].value


def build_listing_filter_values(game_category, option_map, index):
    filter_values = {}
    labels = {}
    assignments = (
        game_category.assigned_filters.select_related("filter")
        .order_by("order", "filter__name")
    )

    for offset, assignment in enumerate(assignments):
        filter_name = assignment.filter.name
        options = option_map[filter_name]
        option = options[(index + offset + game_category.game.order) % len(options)]
        filter_values[str(assignment.filter_id)] = option.value
        labels[filter_name] = option.label

    return filter_values, labels


def build_listing_title(game_category, labels, index):
    game_name = game_category.game.name
    category_slug = game_category.category.slug
    sequence = f"Demo #{index + 1:03d}"
    region = labels.get("Region", "Global")
    platform = labels.get("Platform", "PC")
    rank = labels.get("Rank", "Ranked")
    delivery = labels.get("Delivery Time", "Same Day")
    account_level = labels.get("Account Level", "High Level")
    skins_count = labels.get("Skins Count", "Many")
    item_type = labels.get("Item Type", "Bundle")
    server = labels.get("Server", region)
    language = labels.get("Language", "English")

    if category_slug == "accounts":
        return (
            f"{game_name} {rank} {account_level} Account - "
            f"{skins_count} skins - {region} - {sequence}"
        )
    if category_slug == "top-up":
        return f"{game_name} {item_type} Top-Up - {server} - {delivery} - {sequence}"
    if category_slug == "items":
        return f"{game_name} {item_type} Pack - {platform} - {delivery} - {sequence}"
    if category_slug == "boosting":
        return f"{game_name} {rank} Boosting Service - {platform} - {delivery} - {sequence}"
    if category_slug == "coaching":
        return f"{game_name} {rank} Coaching - {language} - {platform} - {sequence}"
    if category_slug == "gift-cards":
        return f"{game_name} Gift Card Code - {region} - {delivery} - {sequence}"
    if category_slug == "currency":
        return f"{game_name} {item_type} Currency Bundle - {server} - {sequence}"
    return f"{game_name} Marketplace Listing - {sequence}"


def build_listing_description(game_category, labels):
    details = [
        f"Seeded demo listing for {game_category.game.name} {game_category.category.name}.",
        "Use this data to test browse pages, filters, pagination, listing detail pages, and checkout flow.",
    ]
    if labels:
        filter_text = ", ".join(f"{name}: {value}" for name, value in sorted(labels.items()))
        details.append(f"Filters: {filter_text}.")
    details.append("Delivery details are examples for local development only.")
    return " ".join(details)


def build_listing_price(category_slug, game_order, index):
    base_prices = {
        "accounts": 2200,
        "top-up": 450,
        "items": 700,
        "boosting": 1500,
        "coaching": 1200,
        "gift-cards": 1000,
        "currency": 550,
    }
    base = base_prices.get(category_slug, 900)
    variation = ((game_order * 211) + (index * 137)) % 12500
    return Decimal(base + variation).quantize(Decimal("0.01"))


def upsert_listing(seller, game_category, title, description, price, quantity, filter_values):
    listing = (
        Listing.objects.filter(
            seller=seller,
            game_category=game_category,
            title=title,
        )
        .order_by("id")
        .first()
    )
    defaults = {
        "description": description,
        "price": price,
        "quantity": quantity,
        "status": "active",
        "filter_values": filter_values,
    }
    if not listing:
        return Listing.objects.create(
            seller=seller,
            game_category=game_category,
            title=title,
            **defaults,
        )
    return update_fields(listing, defaults)


def seed_listings(game_categories, option_map, sellers):
    quantity_options = [None, 1, 2, 3, 5, 10, 25]
    created_or_updated = 0

    for game_category in game_categories:
        key = (game_category.game.slug, game_category.category.slug)
        listing_count = LARGE_LISTING_SETS.get(
            key,
            BASE_LISTINGS_PER_CATEGORY.get(game_category.category.slug, 8),
        )

        for index in range(listing_count):
            filter_values, labels = build_listing_filter_values(game_category, option_map, index)
            seller = sellers[(index + game_category.game.order) % len(sellers)]
            title = build_listing_title(game_category, labels, index)
            description = build_listing_description(game_category, labels)
            price = build_listing_price(game_category.category.slug, game_category.game.order, index)
            quantity = quantity_options[(index + game_category.game.order) % len(quantity_options)]
            upsert_listing(
                seller=seller,
                game_category=game_category,
                title=title,
                description=description,
                price=price,
                quantity=quantity,
                filter_values=filter_values,
            )
            created_or_updated += 1

    return created_or_updated


def upsert_category_option(game_category, name, order, is_popular):
    option = (
        CategoryOption.objects.filter(game_category=game_category, name=name)
        .order_by("id")
        .first()
    )
    defaults = {"order": order, "is_popular": is_popular}
    if not option:
        return CategoryOption.objects.create(
            game_category=game_category, name=name, **defaults,
        )
    return update_fields(option, defaults)


def upsert_offer_listing(seller, game_category, option, price, delivery_time, filter_values,
                         delivery_instructions):
    listing = (
        Listing.objects.filter(seller=seller, game_category=game_category, option=option)
        .order_by("id")
        .first()
    )
    defaults = {
        "title": option.name,
        "description": "",
        "price": price,
        "quantity": None,
        "status": "active",
        "delivery_time": delivery_time,
        "filter_values": filter_values,
        "delivery_instructions": delivery_instructions,
    }
    if not listing:
        return Listing.objects.create(
            seller=seller,
            game_category=game_category,
            option=option,
            **defaults,
        )
    return update_fields(listing, defaults)


def seed_offer_mode_demos(games, sellers, filters):
    delivery_times = ["1-2 Hours", "2-6 Hours", "6-12 Hours", "12-24 Hours"]
    # Buyers must pick a region before offers show; alternate offer regions so
    # every region has competing sellers.
    region_filter = filters["Region"]
    region_values = ["global", "pakistan"]
    total = 0

    for demo in OFFER_MODE_DEMOS:
        game = games.get(demo["game_slug"])
        if not game:
            continue
        category = upsert_category(demo["category"])
        game_category = upsert_game_category(game, category, demo["category_order"])
        update_fields(game_category, {"listing_mode": "offer"})

        assignment = upsert_game_category_filter(game_category, region_filter, 0)
        update_fields(assignment, {"require_selection": True})

        for order, option_data in enumerate(demo["options"]):
            option = upsert_category_option(
                game_category,
                option_data["name"],
                order,
                option_data.get("popular", False),
            )
            base_price = option_data["base_price"]
            competing_sellers = 3 + (order % 3)
            for index in range(competing_sellers):
                seller = sellers[(index + order) % len(sellers)]
                markup = Decimal(index * 4 + (order % 2)) / Decimal("100")
                price = (base_price * (Decimal("1.00") + markup)).quantize(Decimal("0.01"))
                region_value = region_values[index % len(region_values)]
                upsert_offer_listing(
                    seller=seller,
                    game_category=game_category,
                    option=option,
                    price=price,
                    delivery_time=delivery_times[(index + order) % len(delivery_times)],
                    filter_values={str(region_filter.id): region_value},
                    delivery_instructions=demo["delivery_instructions"],
                )
                total += 1

    return total


def get_or_create_conversation(user_a, user_b):
    conversation = (
        Conversation.objects.filter(participants=user_a)
        .filter(participants=user_b)
        .order_by("id")
        .first()
    )
    if conversation:
        return conversation
    conversation = Conversation.objects.create()
    conversation.participants.add(user_a, user_b)
    return conversation


def upsert_message(conversation, sender, content, is_read):
    message = (
        Message.objects.filter(conversation=conversation, sender=sender, content=content)
        .order_by("id")
        .first()
    )
    if message:
        return update_fields(message, {"is_read": is_read})
    return Message.objects.create(
        conversation=conversation,
        sender=sender,
        content=content,
        is_read=is_read,
    )


def seed_conversations(buyer, sellers):
    message_sets = [
        (
            sellers[0],
            [
                (buyer, "Hi, is the Valorant account still available?", True),
                (sellers[0], "Yes, instant delivery is available today.", False),
            ],
        ),
        (
            sellers[1],
            [
                (buyer, "Can you deliver PUBG Mobile UC in under one hour?", True),
                (sellers[1], "Yes, send the order and I will process it quickly.", False),
            ],
        ),
        (
            sellers[3],
            [
                (buyer, "Do you offer coaching for Diamond rank?", True),
                (sellers[3], "Yes, I can schedule a replay review and live session.", False),
            ],
        ),
    ]

    for seller, messages in message_sets:
        conversation = get_or_create_conversation(buyer, seller)
        for sender, content, is_read in messages:
            upsert_message(conversation, sender, content, is_read)


def print_summary(demo_buyer, sellers):
    print("")
    print("Seed data complete.")
    print(f"Games: {Game.objects.count()}")
    print(f"Categories: {Category.objects.count()}")
    print(f"Game categories: {GameCategory.objects.count()}")
    print(f"Filters: {Filter.objects.count()}")
    print(f"Filter options: {FilterOption.objects.count()}")
    print(f"Filter assignments: {GameCategoryFilter.objects.count()}")
    print(f"Listings: {Listing.objects.count()}")
    print(f"Conversations: {Conversation.objects.count()}")
    print("")
    print("Demo logins:")
    print(f"Buyer: {demo_buyer.username} / {DEMO_PASSWORD}")
    for seller in sellers:
        print(f"Seller: {seller.username} / {DEMO_PASSWORD}")
    print("")
    print("Good browser pages to inspect:")
    print("/games/valorant/accounts")
    print("/games/pubg-mobile/top-up")
    print("/games/roblox/currency")
    print("/games/pubg-mobile/uc (offer mode)")
    print("/games/free-fire/diamonds (offer mode)")


def main():
    with transaction.atomic():
        games = {data["slug"]: upsert_game(data) for data in GAMES}
        categories = {data["slug"]: upsert_category(data) for data in CATEGORIES}

        game_categories = []
        for game_slug, category_slugs in ASSIGNMENTS.items():
            for order, category_slug in enumerate(category_slugs):
                game_categories.append(
                    upsert_game_category(
                        games[game_slug],
                        categories[category_slug],
                        order,
                    )
                )

        filters = {}
        option_map = {}
        for name, filter_type, options in FILTERS:
            filter_obj = upsert_filter(name, filter_type)
            filters[name] = filter_obj
            option_map[name] = [
                upsert_filter_option(filter_obj, label, value, order)
                for order, (label, value) in enumerate(options)
            ]

        for game_category in game_categories:
            filter_names = CATEGORY_FILTERS[game_category.category.slug]
            for order, filter_name in enumerate(filter_names):
                upsert_game_category_filter(game_category, filters[filter_name], order)

        sellers = [upsert_user(data, "approved") for data in SELLERS]
        buyers = [upsert_user(data, "none") for data in BUYERS]

        listing_total = seed_listings(game_categories, option_map, sellers)
        offer_total = seed_offer_mode_demos(games, sellers, filters)
        seed_conversations(buyers[0], sellers)

    print(f"Seeded or updated {listing_total} demo listings.")
    print(f"Seeded or updated {offer_total} offer-mode demo offers.")
    print_summary(buyers[0], sellers)


main()

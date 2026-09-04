# Product pictures — implementation plan (2026-09-05)

Status: PLAN, nothing built. Shayan wants this slow, one visible piece at a
time, each one live and approved before the next starts. The July 2026
attempt (per-listing upload gallery, everything in one go) was reverted for
being confusing; this plan deliberately has NO per-listing uploads.

## Why (what pictures buy us)

Pictures do not raise web rankings directly. They buy:

1. Presence in Google Images and the image pack inside normal results, where
   every Pakistani competitor already appears and we do not.
2. A thumbnail on Product rich results (216 clicks / 6,820 impressions in the
   3 months to 2026-09-02) and eligibility for free Shopping-tab listings.
3. A real product picture in WhatsApp / social link previews. Today every
   page previews as the same generic banner (`/opengraph-image`).
4. Trust: a shop with no product pictures looks unfinished.

## Where pictures come from (no uploading)

| Listings | Source | Count | Who does it |
|---|---|---|---|
| Gift cards, currency (Robux), subscriptions — tile-based pages | Composed by a script: brand logo already on the site + region flag + amount on a card-shaped template. Our own artwork, nothing copied. | ~2,450 (one per tile) | script |
| Keys, Steam gifts, accounts, rentals — one game per page | One cover per game, copied ONCE from Steam's art CDN into our public bucket (never hot-linked). Trial with 20 games first. | ~600 | script; Shayan fixes the odd wrong one in admin |
| Anything the scripts cannot cover | Admin upload on the game or the option | few | Shayan, optional |

Fazer's catalog `imageurl` was checked on 2026-09-05: brand logos only (PSN
logo on blue, Steam logo, Google Play triangle), no card, no flag, no
amount — the same logo the tiles already show at 36 px. Not a picture source.

Why one image per tile (amount printed) rather than one per brand+region:
Google Images and WhatsApp then show "PSN $50 USA" as a distinct picture,
like the competitors' results. Cost is nil (scripted, ~15 KB each) but new
tiles need the generator to run after seeding — see the maintenance hook in
piece 1.

## Where pictures show

1. Gift-card page tiles: the card picture replaces the small logo; name and
   "From Rs" stay underneath.
2. Listing page: a picture at the top of the main column beside the title
   (card for gift-card listings, cover for game listings). Price box unchanged.
3. Keys / accounts / rentals page header: the game cover once, where the
   56 px icon sits today. Listing cards below stay text-only (same game on
   every card).
4. Invisible but the point: `image` in the Product JSON-LD and the
   `og:image` / Twitter image on listing pages and category pages.
5. Later, optional: order page and email thumbnails, home Popular panels.

## Ground rules

- One piece at a time. Each piece: build → local check → deploy → Shayan
  looks at the live page → next piece.
- Every piece is reversible by reverting its commit; generated images can
  stay in the bucket harmlessly.
- Public bucket only (`get_public_media_storage`, media.gamesbazaar.pk).
  Never a signed URL in page HTML (Ahrefs landmine).
- Reserve space for every picture (fixed aspect-ratio box) so CLS stays at
  zero — mobile CLS was fixed once already, do not undo it.
- Nothing touches keys/accounts category pages before 2026-09-27 (PKR-price
  title hold). Gift-card tiles and gift-card listing pages are outside the hold.
- Descriptive filenames (`playstation-usa-50-usd.webp`) and alt text = the
  tile / listing title. Both help image search.
- WebP, at most ~40 KB per tile image, lazy-loaded on tiles.

## Pieces

### Piece 0 — mockup, no site code

Static mockup of (a) the PSN gift-card tile grid with card pictures, both
themes, desktop + mobile, and (b) one listing page with the picture. Shayan
approves the card design: layout, aspect ratio (3:2 proposed), how the flag
and amount sit, colours per brand. Nothing is built until this is approved.

### Piece 1 — PSN tiles get pictures

Backend
- New field `CategoryOption.image` (ImageField, `upload_to='option_images/'`,
  public storage) + migration. Keep the existing 36 px `icon` untouched — the
  Select dropdown and 646 tiles use it today.
- Option serializer gains `image_url`. Browse cache key `browse:v6` → `v7`
  (payload shape change; July gotcha).
- Management command `generate_option_images --game <slug> | --all
  [--missing (default) | --force]`: for every option with active listings,
  compose logo + flag + amount → 900×600 WebP → `option.image`. Idempotent.
  Inputs kept in `backend/core/data/option_image_brands.json` (brand →
  logo file, background colour, text colour) and a region map (label in the
  option name → ISO code, with special badges for Global / Europe / LATAM /
  MENA / CIS / Asia). Amount parsed from the option name.
- Tooling: Pillow (installed) for composition and text; Inter TTF vendored
  (OFL); flags = the MIT `flag-icons` SVGs rasterised once to PNG with the
  `sharp` already in `frontend/node_modules` and committed under
  `backend/core/data/flags/`.
- Admin: field visible on CategoryOption.

Frontend
- Tile: `image_url` shown as a full-width card in a fixed 3:2 box above the
  name; falls back to the old 36 px icon when absent. Buy box shows the same
  image small.

Verify
- `/games/playstation/gift-cards` on prod, light + dark, mobile; Lighthouse
  CLS unchanged; tile images at most ~40 KB; `image_url` absent → old look.

Maintenance hook
- Denominations come and go with the daily sync, so new tiles need pictures:
  add `generate_option_images --all --missing` to the daily `.bat` (Shayan's
  `tools/`, ask before editing) or as a small systemd timer on the server.
  Decide in piece 2.

Rollback: revert the frontend commit (tiles ignore `image_url`); images stay.

### Piece 2 — every other tile page

Brand config for the remaining gift-card brands + currency (Roblox) +
subscriptions (PS Plus, Game Pass). Run the generator for all (~2,450 images,
~40 MB). Shayan reviews brand pages one by one; a brand whose art he dislikes
gets its config changed and regenerated. Wire the maintenance hook.

### Piece 3 — listing page picture + link previews (gift-card listings)

Backend
- `image_url` on the listing serializer: `option.image` → (piece 4)
  `game.cover` → null.

Frontend
- Listing page: picture in a fixed-ratio box at the top of the main column.
- `app/listing/[id]/layout.js` `generateMetadata`: `openGraph.images` and
  the Twitter image = `image_url` when present, else the banner.
- `productJsonLd` `image` = `image_url` when present (the July fallback stays
  for listings without one).
- Brand gift-card page (`/games/<brand>/gift-cards`) and region pages:
  `og:image` = a generic brand card (same generator, no amount).

Verify
- Rich Results Test on one PSN listing shows the card image.
- Share a listing link to yourself on WhatsApp → card preview (use the
  Facebook Sharing Debugger to refresh a stale preview).
- Note: Next caches SSR HTML for days, so old listing pages pick up the
  picture as they revalidate. `indexnow_ping --paths` optional.

### Piece 4 — game covers (after 2026-09-27)

Backend
- New field `Game.cover` (ImageField, `upload_to='game_covers/'`, public
  storage) + migration; `cover_url` on game serializers; admin field.
- Management command `fetch_game_covers [--limit 20] [--game <slug>]`:
  app id from `FazerProductLink` (gift/gamekey links carry it) and
  `tools/fazer_aliases.json` / key map; fetch
  `cdn.akamai.steamstatic.com/steam/apps/<appid>/header.jpg` once, 1 request
  per second, store as 920×430 WebP. Reports games with no app id (Shayan
  uploads those in admin if he wants). **Trial: 20 games, Shayan looks,
  keep or delete.** Never hot-link Steam.

Frontend
- Keys / gifts / accounts / rentals page header shows the cover (icon stays
  in the compact spots: navbar search, popular panels, /games grid).
- Listing page picture for standard listings = cover; `og:image` +
  Product `image` = cover; category page `og:image` = cover.

Verify: 3 pages live, Rich Results Test, WhatsApp preview, CLS.

### Piece 5 — image sitemap

`app/sitemap.js` / `sitemap-listings`: add `images: [url]` to each listing
entry (App Router sitemap supports it). One deploy, then confirm in Search
Console that the sitemap was re-read.

### Piece 6 — optional polish, later

Order page + review-request email thumbnails; home Popular panels with
covers; a card image on the home hero.

## Effort (rough)

| Piece | Time |
|---|---|
| 0 mockup | a few hours |
| 1 PSN tiles | ~1 day incl. migration, generator, tests |
| 2 all brands | half a day + Shayan's review time |
| 3 listing page + previews | half a day |
| 4 game covers | ~1 day (after 09-27) |
| 5 sitemap | 1–2 hours |

## Risks and landmines

- Copyright: brand logos and Steam key art are the publishers'. Every key
  and gift-card shop shows them; publishers ship press kits for exactly this.
  Accepted, same exposure as the logos already on the site. Copy never calls
  anything an "official GamesBazaar" product.
- Steam: the price sync already calls the Steam store daily; a one-time copy
  of ~600 covers at 1/s is a fraction of that. Hot-linking would be the
  harmful version — we copy once into our bucket.
- Tile page weight: PSN has 313 tiles; lazy loading + small WebP keeps the
  page light. Measure before/after with Lighthouse on mobile.
- Dark mode: cards carry their own background colour, so they look the same
  in both themes; the box around them uses theme tokens.
- Tools: any `.bat` change is Shayan's territory — ask first.
- Deploy order as always: frontend build → migrate → restart backend.

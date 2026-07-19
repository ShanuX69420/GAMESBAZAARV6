# GamesBazaar — project handbook

gamesbazaar.pk — Pakistani gaming marketplace (accounts, keys, top-ups, gift cards),
PKR only. Solo developer (Shayan). Live in production, pre-public-launch.

## Working with Shayan

- Plain-language summaries — explain like to a smart non-expert, no jargon walls.
- "go ahead" = execute end-to-end, including production changes.
- Commit/push only after he has reviewed and confirmed. Never commit unprompted.
- Always state clearly BEFORE doing something that touches production.
- His local dev servers usually already run on :3000 (frontend) and :8000 (backend) —
  reuse them, don't restart or spawn duplicates.
- `tools/` contains his local seeding scripts — several are untracked on purpose.
  Never commit anything under `tools/` without asking.

## Layout

| Path | What |
|---|---|
| `backend/` | Django 5.2 + DRF + Channels. Single app: `core`. Run from `backend/` with `python manage.py ...` |
| `backend/core/jazzcash.py` | JazzCash MWallet gateway client (secure hash, initiate, status inquiry) |
| `backend/core/consumers.py` | WebSocket chat/notifications (Channels, daphne) |
| `frontend/` | Next.js 16 App Router, React 19, plain JS. **Read `frontend/AGENTS.md` first** — this Next.js version differs from training data; check `node_modules/next/dist/docs/` before writing Next code |
| `deploy/` | Versioned copies of prod nginx + systemd units. **Nothing syncs automatically** — if you change a file here, copy it to the server too (and vice versa). See `deploy/README.md` |
| `docs/` | `production-deployment.md` (env checklist), `jazzcash-golive-runbook.md` (JazzCash production cutover) |
| `GamesBazaar_Deployment_Runbook.md` | THE deploy guide — follow it for every prod deploy |

## Commands

- Backend tests: `python manage.py test core` (JazzCash suite: `python manage.py test core.test_jazzcash`)
- Frontend tests: `npm test` (vitest, in `frontend/`)
- Local dev: backend `python manage.py runserver`, frontend `npm run dev`

## Production

- DigitalOcean VPS `68.183.184.129` (**Singapore / SGP1**, Premium AMD 2 vCPU / 4 GB
  since 2026-07-19). Domains: gamesbazaar.pk, www, api.
  Migrated out of Bangalore on 2026-07-14 — see the India landmine below. **Never move it
  back to an Indian region.** DNS is Cloudflare, 3 A records (apex/www/api), TTL 300s,
  proxy OFF (grey cloud — the orange cloud made the site slower, don't re-enable).
- SSH: `ssh -i C:\Users\pc\.ssh\gamesbazaar_digitalocean_ed25519 root@68.183.184.129`
  — then run git/pip/manage.py as `sudo -u gamesbazaar`.
- App at `/opt/gamesbazaar/app`, venv `/opt/gamesbazaar/venv`.
- Services: `gamesbazaar-web` (gunicorn :8001 — ALL plain HTTP),
  `gamesbazaar-backend` (daphne :8000 — websockets `/ws/` ONLY; nginx does the
  split), `gamesbazaar-frontend`. Restart BOTH backend halves after a backend deploy.
  Timers: auto-confirm + reconcile-jazzcash (10 min), release-holds (30 min),
  db-backup (nightly 21:30 UTC → R2 `db-backups/`).
- Deploy order matters: **frontend build BEFORE migrate, restart backend right after
  migrate** — otherwise old code hits the new schema for minutes.
- `NEXT_PUBLIC_*` vars are baked in at build time — changing one on the server
  requires `npm run build` + restart, not just a service restart.
- Monitoring: Sentry (backend + frontend projects), UptimeRobot.

## Secrets

- `backend/.env` (local) and `/opt/gamesbazaar/app/backend/.env` +
  `/opt/gamesbazaar/app/frontend/.env.production` (server) hold ALL secrets.
  Gitignored. Never commit, never print in recorded demos/screenshots.
- Prod feature-toggling convention: pending features' env lines are commented with
  `# PENDING-APPROVAL # ` prefix and flipped with sed (see the JazzCash runbook).

## Landmines (learned the hard way — do not relearn)

- **Never mutate Channels channel-layer event dicts** in consumers. The same dict
  object is delivered to every group member in-process; mutating it leaks one
  user's view to another (prod-only chat "You" label bug, commit 5346701).
  Copy the dict before changing it.
- **JazzCash return URL must EXACTLY match the merchant-portal registration**
  (scheme, host, path — `www.` vs bare domain matters) or initiation fails with
  code 999 "insufficient merchant information". Registered: `https://gamesbazaar.pk/wallet`.
- **JazzCash's WAF geo-blocks INDIA — never host this app in an Indian region.**
  Symptom: `JazzCash returned non-JSON response (HTTP 200)` and an HTML "Request
  Rejected" page with a support ID. It is NOT an IP-reputation or datacenter issue
  and NOT fixable by whitelisting: proven 2026-07-14 by probing `pgw.jazzcash.com.pk`
  from five origins — PK residential, PK datacenter and SG datacenter all returned
  JSON; an unrelated Indian VPN IP and our Bangalore VPS both got "Request Rejected".
  SG and IN were the *same VPN vendor*, so country was the only variable. Fix was to
  move the server to Singapore (2026-07-14), not to chase a whitelist. Assume every
  Pakistani payment provider (Easypaisa next) does the same. Inbound (their IPN → us)
  was never affected.
- **Pakistan↔India is network-FAR despite being geographically close** — there is
  essentially no direct PK–IN peering, so traffic detours via Europe/Singapore.
  Measured from Karachi: Bangalore **164 ms**, Singapore **80 ms**, Frankfurt ~120 ms,
  Nayatel (in-country) 25 ms. Singapore is *twice as fast* as Bangalore was. Never
  estimate Pakistani latency from a map — measure it.
- **Hosts selling "Pakistan VPS" are usually not in Pakistan.** MiddleHost's own
  datacenter page lists Dallas/Montreal/London/Amsterdam/Frankfurt and zero PK metal
  (Dallas ≈ 250 ms from Karachi). The tell is marketing that talks about *routing*
  ("optimized routes for PTCL/Nayatel/Stormfiber") instead of naming a city. Latency
  cannot be faked — ping before believing. Nayatel is the only verified real-PK host.
- **Never leave the live server pointed at JazzCash's sandbox** — a sandbox
  payment matching a real txn record would credit a real wallet with fake money.
  Sandbox creds on prod are for short, monitored windows only.
- Piping Python over ssh from PowerShell strips double quotes — use repo
  management commands for remote one-offs, not ad-hoc `python -c` scripts.
- GA events fired before gtag loads rely on queueing stubs installed at module-eval
  time in `frontend/components/Analytics.js` — don't regress. Meta's fbevents.js
  silently drops ALL events when UA contains "HeadlessChrome" or
  `navigator.webdriver` is true — mask both when testing pixels headlessly.
- Dependent filters: "As a Gift" showing on PS/Xbox keys categories is a KNOWN,
  ACCEPTED tradeoff — don't "fix" it unprompted.
- **NEVER run `copy_category_filters --game steam --category keys` again.** That
  command copies the SOURCE page's filters onto EVERY page with that category,
  and steam/keys stopped being the canonical template on 2026-07-13 — it is now
  a Method-less catch-all with its own page-local Region filter. Running it
  pushed that Region filter onto all 309 other keys pages (dead dropdown on
  every game page + listings failing validation; undone by
  `tools/fix_stray_steam_filter_server.py`). New keys pages are healed instead
  by `fazer_sync_lib.HEAL_SNIPPET`, which attaches Method + the two dependent
  Region filters directly to the pages that lack them. If you ever do need to
  copy filters, copy from a page that has the shape you want on the target.
- Local dev `.env.local` deliberately has NO GA measurement id (keeps dev traffic
  out of analytics).

## Payments state (2026-07-14)

- **JazzCash is LIVE on production** since 2026-07-14 (merchant `10030551`, production
  host `pgw.jazzcash.com.pk`). Proven with a real PKR 500 top-up on the live site:
  code `000`, wallet credited exactly once. Wallet payments only (no cards).
  Two things had to be true: production creds (commit `0ab9437` — production endpoints
  + mandatory signed `pp_SubMerchantName`), and getting the server OUT of India.
- `JAZZCASH_ENABLED` derives from the four `JAZZCASH_*` env vars (settings.py) — there
  is **no separate switch; setting those vars IS going live.** Kill switch: re-comment
  them with `# PENDING-APPROVAL # ` and restart (see the go-live runbook).
- IPN endpoint: `/api/payments/jazzcash/ipn/` — hash-authenticated, returns signed ack,
  logs the full exchange at INFO (commit 819aa44).
- Three paths can resolve a payment: IPN callback, user-return status check, and
  the reconcile timer — all feed `apply_gateway_result`.
- Merchant fee: 1.16% incl. FED (mobile wallets), deducted from settlement.
- Roadmap (decided, NOT started): direct checkout + flat buyer service fee, add
  cards + Easypaisa, retire mandatory top-ups but keep the wallet for seller
  earnings and instant refund credit. No flow changes while JazzCash approval is
  pending.
- Go-live day: follow `docs/jazzcash-golive-runbook.md`.

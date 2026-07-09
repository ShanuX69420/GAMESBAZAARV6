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

- DigitalOcean VPS `64.227.182.238` (Bangalore, 1 GB). Domains: gamesbazaar.pk, www, api.
- SSH: `ssh -i C:\Users\pc\.ssh\gamesbazaar_digitalocean_ed25519 root@64.227.182.238`
  — then run git/pip/manage.py as `sudo -u gamesbazaar`.
- App at `/opt/gamesbazaar/app`, venv `/opt/gamesbazaar/venv`.
- Services: `gamesbazaar-backend` (daphne :8000), `gamesbazaar-frontend`.
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
- **JazzCash's WAF blocks outbound API calls from the VPS IP.** Symptom:
  `JazzCash returned non-JSON response (HTTP 200)` and an HTML "Request Rejected"
  page. Whitelisting of 64.227.182.238 was requested 2026-07-06. If the server IP
  ever changes (migration, new droplet), get the NEW IP whitelisted by JazzCash
  BEFORE switching. Inbound (their IPN → us) is not affected.
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
  ACCEPTED tradeoff — don't "fix" it unprompted. After catalog changes re-run
  `manage.py copy_category_filters --game steam --category keys` (adds/updates,
  never deletes).
- Local dev `.env.local` deliberately has NO GA measurement id (keeps dev traffic
  out of analytics).

## Payments state (2026-07-06)

- JazzCash MWallet v1.1, wallet payments only (no cards) — production approval in
  progress; UAT evidence submitted. `JAZZCASH_ENABLED` derives from the four
  `JAZZCASH_*` env vars (settings.py). IPN endpoint:
  `/api/payments/jazzcash/ipn/` — hash-authenticated, returns signed ack, logs the
  full exchange at INFO (commit 819aa44).
- Three paths can resolve a payment: IPN callback, user-return status check, and
  the reconcile timer — all feed `apply_gateway_result`.
- Merchant fee: 1.16% incl. FED (mobile wallets), deducted from settlement.
- Roadmap (decided, NOT started): direct checkout + flat buyer service fee, add
  cards + Easypaisa, retire mandatory top-ups but keep the wallet for seller
  earnings and instant refund credit. No flow changes while JazzCash approval is
  pending.
- Go-live day: follow `docs/jazzcash-golive-runbook.md`.

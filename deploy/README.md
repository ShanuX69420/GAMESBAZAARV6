# Server configuration (disaster-recovery copies)

Versioned copies of the production server's configuration, so the whole
machine can be rebuilt from this repo plus the nightly database backups
(R2 bucket, `db-backups/` prefix).

| File | Lives on the server at |
|---|---|
| `nginx/gamesbazaar.conf` | `/etc/nginx/sites-available/gamesbazaar` (symlinked into `sites-enabled/`) |
| `nginx/api-cache.conf` | `/etc/nginx/conf.d/api-cache.conf` (proxy-cache zone — `gamesbazaar.conf` fails `nginx -t` without it) |
| `nginx/timing.conf` | `/etc/nginx/conf.d/timing.conf` (request-timing `log_format` → `/var/log/nginx/timing.log`; `gamesbazaar.conf` fails `nginx -t` without it) |
| `nginx/gamesbazaar-upgrade-map.conf` | `/etc/nginx/conf.d/gamesbazaar-upgrade-map.conf` (defines `$connection_upgrade`; `gamesbazaar.conf` fails `nginx -t` without it) |
| `nginx/rate-limit.conf` | `/etc/nginx/conf.d/rate-limit.conf` (per-IP `limit_req` zones + the server-IP exemption; `gamesbazaar.conf` fails `nginx -t` without it) |
| `fail2ban/jail.local` | `/etc/fail2ban/jail.local` (the two nginx-log jails; `apt install fail2ban` first) |
| `fail2ban/filter.d/*.conf` | `/etc/fail2ban/filter.d/` (scanner-signature and 429-flood filters) |
| `systemd/*.service`, `systemd/*.timer` | `/etc/systemd/system/` |
| `backup_db.py` | `/opt/gamesbazaar/backup_db.py` (chmod 750) |

App services: `gamesbazaar-web` (gunicorn WSGI, 127.0.0.1:8001) serves ALL
backend HTTP — there are no websockets since the 2026-08 shop conversion
(the old `gamesbazaar-backend` daphne service was retired with it).
After a backend code deploy, restart `gamesbazaar-web`.

Timers: `reconcile-jazzcash` every 10 min, `fazer-fulfill` every 1 min (Fazer
auto-fulfillment driver — safety net behind the in-process worker),
`review-requests` every 15 min (post-purchase "leave a review" emails —
top-ups/gift cards asked ~3 h after completion, accounts/keys after ~24 h),
`db-backup` nightly at 21:30 UTC (02:30 PKT),
`indexnow` every 30 min (pushes changed listing + game-category URLs to Bing
and the other IndexNow engines — needs `INDEXNOW_KEY` in the backend `.env`,
harmless no-op without it; the key is also served as `frontend/public/<key>.txt`).
The old `auto-confirm` and `release-holds` timers were retired with escrow in
the 2026-08 shop conversion — orders complete on delivery, nothing is held.
After copying units: `systemctl daemon-reload && systemctl enable --now <name>.timer`.

Secrets are NOT in this folder — they live only in
`/opt/gamesbazaar/app/backend/.env` and
`/opt/gamesbazaar/app/frontend/.env.production` on the server.
If you change a config here, copy it to the server too (and vice versa) —
nothing syncs these automatically.

## Rate limiting and scanner bans (2026-09-08)

Two layers, added after a four-hour SQL-injection scan from one IP
(~54,800 requests, 477 Sentry alerts, 55 fake Buy-on-WhatsApp clicks).

- **nginx `limit_req`** (`nginx/rate-limit.conf` + the `limit_req` lines in
  `nginx/gamesbazaar.conf`): 15 r/s per IP on www page routes (burst 60),
  30 r/s per IP on the API (burst 100), excess answered `429` at once.
  `/_next/static/` and `/_next/image` are outside the limit (a page load
  fetches dozens). Loopback and the droplet's own IP are exempt — Next's SSR
  fetches hit `api.gamesbazaar.pk` from the public IP. This is a flood
  backstop, not scanner detection: a polite scanner stays under it on purpose,
  because Pakistani ISPs put many buyers behind one CGNAT address.
- **fail2ban** (`fail2ban/`): `gamesbazaar-scanner` bans for 24 h after six
  injection/probe signatures in ten minutes (`sleep(`, `waitfor delay`,
  `union select`, `' or 1=1`, `<script`, `wp-login.php`, `.env`, …);
  `gamesbazaar-flood` bans for 30 min after 100 `429`s in five minutes. Bans
  are ufw rules (`ufw status` lists them). Real browsers never trip the
  first; the second needs a sustained flood. Both ignore the droplet's own IP.

```
fail2ban-client status                       # jails
fail2ban-client status gamesbazaar-scanner   # who is banned
fail2ban-client set gamesbazaar-scanner unbanip 1.2.3.4
fail2ban-regex /var/log/nginx/access.log /etc/fail2ban/filter.d/gamesbazaar-scanner.conf   # dry run
```

If the droplet's IP ever changes, update it in BOTH `nginx/rate-limit.conf`
(geo block) and `fail2ban/jail.local` (`ignoreip`), or the site rate-limits
and eventually bans its own page rendering.

Rebuild-from-scratch gotchas (hit during the 2026-08-27 droplet migration):
- `mkdir -p /var/cache/nginx/api && chown -R www-data:www-data /var/cache/nginx`
  before `nginx -t` — `api-cache.conf` points its proxy cache there.
- `/opt/gamesbazaar` must be mode 755 (`adduser --system` creates it 750,
  which breaks nginx's access to `backend/staticfiles/`).

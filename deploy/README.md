# Server configuration (disaster-recovery copies)

Versioned copies of the production server's configuration, so the whole
machine can be rebuilt from this repo plus the nightly database backups
(R2 bucket, `db-backups/` prefix).

| File | Lives on the server at |
|---|---|
| `nginx/gamesbazaar.conf` | `/etc/nginx/sites-available/gamesbazaar` (symlinked into `sites-enabled/`) |
| `systemd/*.service`, `systemd/*.timer` | `/etc/systemd/system/` |
| `backup_db.py` | `/opt/gamesbazaar/backup_db.py` (chmod 750) |

Timers: `auto-confirm` and `reconcile-jazzcash` every 10 min,
`release-holds` every 30 min, `db-backup` nightly at 21:30 UTC (02:30 PKT).
After copying units: `systemctl daemon-reload && systemctl enable --now <name>.timer`.

Secrets are NOT in this folder — they live only in
`/opt/gamesbazaar/app/backend/.env` and
`/opt/gamesbazaar/app/frontend/.env.production` on the server.
If you change a config here, copy it to the server too (and vice versa) —
nothing syncs these automatically.

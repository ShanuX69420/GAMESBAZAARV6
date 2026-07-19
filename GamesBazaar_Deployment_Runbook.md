# GamesBazaar Deployment Runbook

Last updated: May 23, 2026

This file is your quick guide for deploying GamesBazaar when you need to do it yourself.

The normal flow is:

```text
Local PC -> commit code -> push to GitHub -> SSH into VPS -> pull latest code -> build/migrate -> restart services -> verify live site
```

Do not directly edit files on the VPS unless it is an emergency. GitHub should be the source of truth.

---

## Server Info

VPS IP:

```text
68.183.184.129
```

Main domain:

```text
gamesbazaar.pk
www.gamesbazaar.pk
api.gamesbazaar.pk
```

App folder on VPS:

```bash
/opt/gamesbazaar/app
```

SSH key on your Windows PC:

```powershell
C:\Users\pc\.ssh\gamesbazaar_digitalocean_ed25519
```

SSH into the server from Windows PowerShell:

```powershell
ssh -i C:\Users\pc\.ssh\gamesbazaar_digitalocean_ed25519 root@68.183.184.129
```

After you SSH in, you are running Linux commands on the VPS.

---

## Important Services

These are the main services:

```bash
gamesbazaar-web       # gunicorn — serves ALL normal HTTP requests (:8001)
gamesbazaar-backend   # daphne — serves ONLY websockets /ws/ (:8000)
gamesbazaar-frontend
nginx
postgresql
redis-server
```

Check if everything is running:

```bash
systemctl is-active gamesbazaar-web gamesbazaar-backend gamesbazaar-frontend nginx postgresql redis-server
```

You want each line to say:

```text
active
```

---

## Push Code From Your PC To GitHub

Run this in Windows PowerShell:

```powershell
cd C:\Users\pc\opus

git status
# Review the git status output before adding. Never commit .env files,
# anything from backend/secrets/, or one-off local scripts.
git add .
git commit -m "Describe what changed"
git push origin main
```

Then SSH into the VPS and deploy.

---

## Normal Full Deploy

Use this when you pushed new code to GitHub and want the VPS updated.

SSH into the server first:

```powershell
ssh -i C:\Users\pc\.ssh\gamesbazaar_digitalocean_ed25519 root@68.183.184.129
```

Then run:

Order matters: build the frontend BEFORE running migrations. The old backend
keeps serving requests until the restart, so the gap between `migrate` and
`systemctl restart` must stay as short as possible — otherwise old code can
query columns a migration just renamed/removed and visitors see errors.

```bash
cd /opt/gamesbazaar/app

sudo -u gamesbazaar git fetch origin main
sudo -u gamesbazaar git status
sudo -u gamesbazaar git pull --ff-only origin main

cd /opt/gamesbazaar/app/frontend
sudo -u gamesbazaar npm ci
sudo -u gamesbazaar npm run build

cd /opt/gamesbazaar/app/backend
sudo -u gamesbazaar /opt/gamesbazaar/venv/bin/pip install -r requirements.txt
sudo -u gamesbazaar /opt/gamesbazaar/venv/bin/python manage.py collectstatic --noinput
sudo -u gamesbazaar /opt/gamesbazaar/venv/bin/python manage.py check --deploy --fail-level ERROR
sudo -u gamesbazaar /opt/gamesbazaar/venv/bin/python manage.py migrate --noinput

systemctl restart gamesbazaar-web gamesbazaar-backend gamesbazaar-frontend

systemctl is-active gamesbazaar-web gamesbazaar-backend gamesbazaar-frontend nginx postgresql redis-server
```

If all services say `active`, the deploy probably worked.

---

## Quick Frontend-Only Deploy

Use this if you only changed frontend code, such as React, CSS, Next.js pages, or UI.

```bash
cd /opt/gamesbazaar/app
sudo -u gamesbazaar git pull --ff-only origin main

cd /opt/gamesbazaar/app/frontend
sudo -u gamesbazaar npm run build

systemctl restart gamesbazaar-frontend
systemctl is-active gamesbazaar-frontend
```

---

## Quick Backend-Only Deploy

Use this if you only changed backend Python/Django code.

```bash
cd /opt/gamesbazaar/app
sudo -u gamesbazaar git pull --ff-only origin main

cd /opt/gamesbazaar/app/backend
sudo -u gamesbazaar /opt/gamesbazaar/venv/bin/pip install -r requirements.txt
sudo -u gamesbazaar /opt/gamesbazaar/venv/bin/python manage.py migrate --noinput
sudo -u gamesbazaar /opt/gamesbazaar/venv/bin/python manage.py collectstatic --noinput
sudo -u gamesbazaar /opt/gamesbazaar/venv/bin/python manage.py check --deploy --fail-level ERROR

systemctl restart gamesbazaar-web gamesbazaar-backend
systemctl is-active gamesbazaar-web gamesbazaar-backend
```

---

## Restart Commands

Restart backend (both halves — gunicorn HTTP + daphne websockets):

```bash
systemctl restart gamesbazaar-web gamesbazaar-backend
```

Restart frontend:

```bash
systemctl restart gamesbazaar-frontend
```

Restart both app services:

```bash
systemctl restart gamesbazaar-web gamesbazaar-backend gamesbazaar-frontend
```

Restart Nginx:

```bash
systemctl restart nginx
```

Reload Nginx after config changes:

```bash
systemctl reload nginx
```

---

## Logs

Backend logs:

```bash
journalctl -u gamesbazaar-backend -n 80 --no-pager
```

Frontend logs:

```bash
journalctl -u gamesbazaar-frontend -n 80 --no-pager
```

Nginx logs:

```bash
journalctl -u nginx -n 80 --no-pager
```

Follow backend logs live:

```bash
journalctl -u gamesbazaar-backend -f
```

Follow frontend logs live:

```bash
journalctl -u gamesbazaar-frontend -f
```

Press `Ctrl+C` to stop following logs.

---

## Health Checks

Check frontend:

```bash
curl -I -L https://gamesbazaar.pk/login
```

Check API:

```bash
curl -I https://api.gamesbazaar.pk/api/games/
```

Good result:

```text
HTTP/1.1 200 OK
```

The main domain may first return `301 Moved Permanently` to redirect to `www.gamesbazaar.pk`. That is okay as long as the final result is `200 OK`.

---

## If Git Pull Refuses

Sometimes the server says local files were modified.

First check:

```bash
cd /opt/gamesbazaar/app
sudo -u gamesbazaar git status
```

Safe backup option:

```bash
sudo -u gamesbazaar git stash push -m "backup before deploy"
sudo -u gamesbazaar git pull --ff-only origin main
```

List stashes:

```bash
sudo -u gamesbazaar git stash list
```

Do not run this unless you are 100% okay deleting uncommitted server edits:

```bash
sudo -u gamesbazaar git reset --hard
```

---

## Database Backup

Before risky updates, create a database backup:

```bash
sudo -u postgres pg_dump gamesbazaar > /root/gamesbazaar-backup-$(date +%F-%H%M).sql
```

List backups:

```bash
ls -lh /root/gamesbazaar-backup-*.sql
```

---

## Cron Jobs / Timers

GamesBazaar uses systemd timers for scheduled jobs.

List timers:

```bash
systemctl list-timers | grep gamesbazaar
```

Check auto-confirm orders timer:

```bash
systemctl status gamesbazaar-auto-confirm.timer
```

Check release held funds timer:

```bash
systemctl status gamesbazaar-release-holds.timer
```

Check JazzCash reconcile timer (settles pending gateway payments via the
mandatory Status Inquiry API; run every 2–3 minutes — JazzCash requires
pending code-157 transactions to be inquired 5–7 minutes after initiation,
and the command itself skips payments younger than 5 minutes):

```bash
systemctl status gamesbazaar-jazzcash-reconcile.timer
```

The underlying command, if you need to run it by hand:

```bash
python manage.py reconcile_jazzcash_payments
```

---

## JazzCash Gateway

Required env vars (backend `.env`): `JAZZCASH_MERCHANT_ID`, `JAZZCASH_PASSWORD`,
`JAZZCASH_INTEGRITY_SALT`, `JAZZCASH_RETURN_URL`. JazzCash payment options stay
hidden in the app until all four are set. `JAZZCASH_MERCHANT_MPIN` is optional
(Refund API only).

In the JazzCash merchant portal (Integration > Credentials) register:

- Return URL — must match `JAZZCASH_RETURN_URL` exactly (sent on every request).
- IPN URL — `https://<api-host>/api/payments/jazzcash/ipn/`

Payments admin: Django admin → JazzCash payments (read-only, with a
"Run JazzCash status inquiry" action for stuck transactions).

---

## SSL And Nginx

Test Nginx config:

```bash
nginx -t
```

Reload Nginx:

```bash
systemctl reload nginx
```

Test SSL renewal:

```bash
certbot renew --dry-run
```

---

## Server Resource Checks

Memory:

```bash
free -h
```

Disk:

```bash
df -h
```

CPU/processes:

```bash
top
```

If `htop` is installed:

```bash
htop
```

---

## Environment Files

Backend environment file:

```bash
/opt/gamesbazaar/app/backend/.env
```

Frontend production environment file:

```bash
/opt/gamesbazaar/app/frontend/.env.production
```

Do not commit `.env` files or secrets to GitHub.

If you change backend `.env`, restart backend:

```bash
systemctl restart gamesbazaar-backend
```

If you change frontend `.env.production`, rebuild and restart frontend:

```bash
cd /opt/gamesbazaar/app/frontend
sudo -u gamesbazaar npm run build
systemctl restart gamesbazaar-frontend
```

---

## Common Problems

### Site is down

Check services:

```bash
systemctl is-active gamesbazaar-backend gamesbazaar-frontend nginx postgresql redis-server
```

Then check logs:

```bash
journalctl -u gamesbazaar-backend -n 80 --no-pager
journalctl -u gamesbazaar-frontend -n 80 --no-pager
journalctl -u nginx -n 80 --no-pager
```

### Frontend change is not showing

Run:

```bash
cd /opt/gamesbazaar/app/frontend
sudo -u gamesbazaar npm run build
systemctl restart gamesbazaar-frontend
```

Then hard refresh browser:

```text
Ctrl+F5
```

### Backend change is not showing

Run:

```bash
systemctl restart gamesbazaar-backend
```

### Migration error

Stop and read the error carefully. Do not keep retrying blindly.

Useful command:

```bash
cd /opt/gamesbazaar/app/backend
sudo -u gamesbazaar /opt/gamesbazaar/venv/bin/python manage.py showmigrations
```

---

## Final Deploy Checklist

Use this checklist after every deploy:

```text
[ ] Code pushed to GitHub
[ ] VPS pulled latest main
[ ] Backend requirements installed
[ ] Migrations ran
[ ] Django check passed
[ ] Frontend build passed
[ ] Backend restarted
[ ] Frontend restarted
[ ] Services are active
[ ] Frontend URL returns 200
[ ] API URL returns 200
[ ] No scary errors in logs
```

---

## Most Important Rule

If you are unsure, do this before making risky changes:

```bash
cd /opt/gamesbazaar/app
sudo -u gamesbazaar git status
sudo -u postgres pg_dump gamesbazaar > /root/gamesbazaar-backup-$(date +%F-%H%M).sql
sudo -u gamesbazaar git stash push -m "backup before risky change"
```

Backups first. Then deploy.


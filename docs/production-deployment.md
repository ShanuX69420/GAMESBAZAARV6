# Production Deployment Checklist

Use this checklist before putting GamesBazaar on a public domain.

## Backend Environment

Set these values in the backend hosting environment. Do not commit the real
values to git.

```env
DJANGO_ENV=production
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=replace-with-a-long-random-secret
DJANGO_ALLOWED_HOSTS=api.example.com
FIELD_ENCRYPTION_KEYS=prod-2026-04:replace-with-fernet-key
FIELD_ENCRYPTION_PRIMARY_KEY_ID=prod-2026-04

DB_ENGINE=django.db.backends.postgresql
DB_NAME=gamesbazaar
DB_USER=gamesbazaar_user
DB_PASSWORD=replace-with-database-password
DB_HOST=replace-with-database-host
DB_PORT=5432

CORS_ALLOWED_ORIGINS=https://www.example.com
CSRF_TRUSTED_ORIGINS=https://www.example.com

CHANNEL_REDIS_URL=redis://replace-with-redis-host:6379/0
CACHE_REDIS_URL=redis://replace-with-redis-host:6379/1
JWT_AUTH_COOKIE_SECURE=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
```

Notes:
- `DJANGO_ENV` must be `production` in production. Use `DJANGO_ENV=development` only for local developer machines.
- `DJANGO_DEBUG` must be `False` in production.
- `DJANGO_SECRET_KEY` must be unique, long, and private.
- `FIELD_ENCRYPTION_KEYS` protects stored delivery secrets. Generate a Fernet key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`, keep old keys for reading old encrypted rows, and point `FIELD_ENCRYPTION_PRIMARY_KEY_ID` at the newest key.
- `DJANGO_ALLOWED_HOSTS` must list only real backend hostnames. Do not use `*`.
- `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` must list the frontend origin exactly, including `https://`.
- `CHANNEL_REDIS_URL` is required when `DJANGO_DEBUG=False` because chat uses Channels.
- `CACHE_REDIS_URL` should point to shared Redis for rate limiting. If omitted, the backend falls back to `CHANNEL_REDIS_URL`.
- Keep `JWT_AUTH_COOKIE_SECURE=True` so auth cookies are only sent over HTTPS.

## Frontend Environment

Set these values in the frontend hosting environment:

```env
NEXT_PUBLIC_API_URL=https://api.example.com
NEXT_PUBLIC_WS_URL=wss://api.example.com
```

Notes:
- Use `https://` for the API URL.
- Use `wss://` for the WebSocket URL.
- Do not leave these pointed at `localhost` or `127.0.0.1` in production.

## Release Checks

Run these before deploying:

```powershell
cd backend
python manage.py check --deploy
python manage.py test core

cd ..\frontend
npm run build
```

Expected result:
- `python manage.py check --deploy` should have no serious warnings for the real production environment.
- Backend tests should pass.
- Frontend build should pass.

## After Deploy

Check these manually in the browser:
- Register, login, refresh after page reload, and logout.
- Create a listing as an approved seller.
- Buy a listing with wallet funds.
- Send and receive chat messages.
- Open the wallet page and confirm top-up and transaction history load normally.
- Confirm chat image/payment proof links are not public without permission.

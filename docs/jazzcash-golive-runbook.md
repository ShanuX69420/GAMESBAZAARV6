# JazzCash production go-live runbook

Copy-paste guide for the day JazzCash approves the merchant account and issues
production credentials. Each step has a check — do not move on until the check
passes. Total time if nothing goes wrong: ~30 minutes.

Context: the integration is MWallet v1.1 only (no cards). Payment outcomes are
resolved by three independent paths — the IPN callback, the user returning to
`/wallet`, and the `gamesbazaar-reconcile-jazzcash` timer — so a missed IPN
self-heals within one timer interval.

---

## 0. Prerequisites (all must be true before starting)

1. **Production credentials received** from JazzCash: Merchant ID, password,
   integrity salt (these will be DIFFERENT from the sandbox `MC990370` set).
2. **Server IP whitelisted by JazzCash.** Their F5 WAF blocked our VPS IP
   `64.227.182.238` during UAT (support ID 2070602475517634790, whitelisting
   requested 2026-07-06). Verify from the VPS — this is the #1 go-live blocker:

   ```bash
   curl -s -o /tmp/jc_probe -w "%{http_code} %{content_type}\n" -X POST \
     "https://onlinepayments.jazzcash.com.pk/payment-orchestrator/api/v1/rest/payments/m-wallet" \
     -H "Content-Type: application/json" -d '{}'
   head -c 300 /tmp/jc_probe; echo
   ```

   - **PASS:** response is JSON (an API error object is fine — we sent an empty body).
   - **FAIL:** HTML containing "Request Rejected" → still blocked. Stop; reply to
     JazzCash with the support ID shown in that HTML.
3. **Live merchant-portal access** (the production portal, not sandbox).
4. If JazzCash says the production API lives on a different host than
   `https://onlinepayments.jazzcash.com.pk`, note it — you'll set
   `JAZZCASH_BASE_URL` in step 2.

## 1. Register URLs in the LIVE merchant portal

| Setting | Value |
|---|---|
| Return URL | `https://gamesbazaar.pk/wallet` |
| IPN URL | `https://api.gamesbazaar.pk/api/payments/jazzcash/ipn/` |

**The Return URL in the portal and `JAZZCASH_RETURN_URL` in the server `.env`
must match EXACTLY** — scheme, host (`www.` vs bare), path, everything. A
mismatch fails every initiation with code 999 "insufficient merchant
information". If the portal forces a different value (e.g. it adds `www.`),
use that exact value in step 2 instead.

## 2. Set production env vars on the server

SSH in:

```powershell
ssh -i C:\Users\pc\.ssh\gamesbazaar_digitalocean_ed25519 root@64.227.182.238
```

Edit `/opt/gamesbazaar/app/backend/.env` (e.g. `nano`). Replace the four
JazzCash lines with the PRODUCTION values (remove any `# PENDING-APPROVAL # `
prefixes; make sure no sandbox values remain):

```env
JAZZCASH_MERCHANT_ID=<production merchant id>
JAZZCASH_PASSWORD=<production password>
JAZZCASH_INTEGRITY_SALT=<production integrity salt>
JAZZCASH_RETURN_URL=https://gamesbazaar.pk/wallet
```

Only if JazzCash gave a different production host in step 0.4:

```env
JAZZCASH_BASE_URL=<production base url>
```

`JAZZCASH_ENABLED` switches on automatically when all four core vars are set
(see `backend/gamesbazaar/settings.py`).

Then:

```bash
systemctl restart gamesbazaar-backend
systemctl is-active gamesbazaar-backend   # must print: active
```

## 3. Verify the endpoint is live

From any machine (this sends garbage — the endpoint must REJECT it, signed):

```bash
curl -s -o - -w "\nHTTP %{http_code}\n" -X POST \
  "https://api.gamesbazaar.pk/api/payments/jazzcash/ipn/" \
  -H "Content-Type: application/json" \
  -d '{"pp_TxnRefNo":"probe","pp_ResponseCode":"121","pp_SecureHash":"deadbeef"}'
```

- **PASS:** HTTP 400 with `pp_ResponseCode: "199"` and a `pp_SecureHash` —
  endpoint enabled and signing.
- **FAIL:** HTTP 503 → env vars didn't load; re-check step 2 and the restart.

Also confirm the JazzCash option shows on https://gamesbazaar.pk/wallet.

## 4. (Recommended) Tighten the reconcile timer

The timer exists and runs every 10 minutes. At go-live, 3 minutes gives
customers a faster fallback when an IPN is missed. On the server, edit
`/etc/systemd/system/gamesbazaar-reconcile-jazzcash.timer`:

```ini
OnUnitActiveSec=3min
```

```bash
systemctl daemon-reload
systemctl restart gamesbazaar-reconcile-jazzcash.timer
systemctl list-timers | grep jazzcash   # next run within 3 min
```

Mirror the same edit in the repo copy
`deploy/systemd/gamesbazaar-reconcile-jazzcash.timer` (nothing syncs
automatically) and commit it.

## 5. Real-money smoke test

Watch the logs in one terminal:

```bash
journalctl -u gamesbazaar-backend -f | grep -i jazzcash
```

Then, from your own JazzCash account, do ONE small top-up (PKR 50–100) on the
live site. All of these must be true:

1. The MWallet prompt/OTP flow completes on your phone.
2. Wallet balance increases by exactly the top-up amount, ONCE.
3. Logs show `JazzCash IPN request:` and `JazzCash IPN response:` lines with
   `pp_ResponseCode` 121 (payment) and 000 (our ack).
4. In Django admin, the JazzCashPayment row is `completed`, `wallet_credited=True`.
5. No new Sentry errors.

If the IPN lines never appear but the wallet still credits within ~10 minutes,
the reconcile path did the work — payment flow is fine, but the portal IPN URL
needs re-checking (step 1).

## 6. After the test

- Check settlement in the merchant portal the next business day (fee: 1.16%
  incl. FED, deducted from settlement — customer pays face value).
- Keep an eye on `journalctl -u gamesbazaar-backend | grep -i jazzcash` and
  Sentry for the first few days.

## Rollback (kill switch)

Disables all JazzCash payments immediately (IPN endpoint returns 503, top-up
option disappears; manual admin top-ups keep working):

```bash
sed -i 's/^JAZZCASH_/# PENDING-APPROVAL # JAZZCASH_/' /opt/gamesbazaar/app/backend/.env
systemctl restart gamesbazaar-backend
```

Re-enable later:

```bash
sed -i 's/^# PENDING-APPROVAL # \(JAZZCASH_\)/\1/' /opt/gamesbazaar/app/backend/.env
systemctl restart gamesbazaar-backend
```

## Warnings

- **Never leave sandbox credentials on the production server.** A sandbox
  payment whose `pp_TxnRefNo` matches a real pending record would credit a real
  wallet with fake money. Sandbox-on-prod is for short, monitored windows only
  (as during the 2026-07-06 IPN evidence capture).
- If the server ever moves or gets a new IP, JazzCash must whitelist the NEW IP
  **before** the switch — see the Landmines section in the root `CLAUDE.md`.

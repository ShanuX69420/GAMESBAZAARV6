# JazzCash — production status & operations

**STATUS: LIVE since 2026-07-14.** Merchant ID `10030551`, MWallet v1.1 (wallet payments
only, no cards). Proven with a real PKR 500 top-up on gamesbazaar.pk: `pp_ResponseCode 000`,
wallet credited exactly once.

This file used to be the go-live checklist. Go-live is done — what follows is the
operational reference: how it is configured, how to turn it off, and the two traps that
cost us weeks.

---

## Current configuration (production)

| Setting | Value |
|---|---|
| Merchant ID | `10030551` |
| API host | `https://pgw.jazzcash.com.pk` |
| MWallet v1.1 | `/api/payment/DoTransaction` |
| Status Inquiry | `/ApplicationAPI/API/PaymentInquiry/Inquire` |
| MWallet Refund | `/api/Purchase/domwalletrefundtransaction` |
| Return URL | `https://gamesbazaar.pk/wallet` |
| IPN URL | `https://api.gamesbazaar.pk/api/payments/jazzcash/ipn/` |
| Merchant portal | `https://pgw-portal.jazzcash.com.pk/account/login` |
| Merchant fee | 1.16% incl. FED (mobile wallets), deducted from settlement |

Credentials live in `/opt/gamesbazaar/app/backend/.env` (gitignored). JazzCash issued three
values — Merchant ID, Password, Integrity Salt. `JAZZCASH_RETURN_URL` is ours, not theirs.

`JAZZCASH_BASE_URL` and `JAZZCASH_SUB_MERCHANT_NAME` are deliberately **not set** on the
server — they default correctly in `settings.py`. Only set them if JazzCash move the API or
demand a specific registered sub-merchant name.

---

## THE TWO TRAPS (learned the hard way — do not relearn)

### 1. JazzCash geo-blocks India. Never host this app in an Indian region.

Symptom: `JazzCash returned non-JSON response (HTTP 200)`, and an HTML "Request Rejected"
page carrying an F5 support ID.

This is **not** an IP-reputation problem and **cannot** be fixed by asking them to whitelist
you. Proven 2026-07-14 by sending an identical probe from five origins:

| Origin | Result |
|---|---|
| Pakistan, residential (Karachi) | JSON — allowed |
| Pakistan, **datacenter** (Zenlayer) | JSON — allowed |
| **Singapore, datacenter** | JSON — allowed |
| **India, datacenter** (unrelated VPN IP) | "Request Rejected" |
| Our old VPS (DigitalOcean Bangalore) | "Request Rejected" |

Singapore and India were the *same VPN vendor*, so country was the only variable. We spent
weeks chasing an IP whitelist that was never going to arrive. The fix was moving the server
to Singapore.

**Assume every Pakistani payment provider does this.** Easypaisa is next — expect the same.

Probe from the server whenever you suspect the WAF:

```bash
curl -s -o /tmp/jc -w "%{http_code} %{content_type}\n" -X POST \
  "https://pgw.jazzcash.com.pk/api/payment/DoTransaction" \
  -H "Content-Type: application/json" -d '{}'
head -c 300 /tmp/jc; echo
```

- **PASS:** JSON (an API error object is fine — we sent an empty body).
- **FAIL:** HTML "Request Rejected" → the source IP's country is blocked.

Inbound (their IPN → us) is never affected.

### 2. Never leave the live server pointed at JazzCash's sandbox.

A sandbox payment whose `pp_TxnRefNo` matches a real pending record would credit a real
wallet with fake money. Sandbox merchant ID is `MC990370`; production is `10030551` — check
which one is loaded before any restart that touches the `.env`.

This nearly bit us at go-live: the server's commented-out `JAZZCASH_*` lines still held
**sandbox** credentials, so "just uncomment them" would have pointed production at the
sandbox. Always verify the merchant ID after enabling.

---

## Kill switch

Disables all JazzCash payments immediately — the IPN endpoint returns 503 and the top-up
option disappears from the wallet page. Manual admin top-ups keep working.

```bash
sed -i 's/^JAZZCASH_/# PENDING-APPROVAL # JAZZCASH_/' /opt/gamesbazaar/app/backend/.env
systemctl restart gamesbazaar-backend
```

Re-enable:

```bash
sed -i 's/^# PENDING-APPROVAL # \(JAZZCASH_\)/\1/' /opt/gamesbazaar/app/backend/.env
systemctl restart gamesbazaar-backend
```

`JAZZCASH_ENABLED` is **derived** from the four `JAZZCASH_*` vars (see `settings.py`). There
is no separate flag: **setting those vars IS going live.**

---

## Health checks

**Is the gateway armed?** This sends a forged callback — it must be rejected, and signed:

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST \
  "https://api.gamesbazaar.pk/api/payments/jazzcash/ipn/" \
  -H "Content-Type: application/json" \
  -d '{"pp_TxnRefNo":"probe","pp_ResponseCode":"121","pp_SecureHash":"deadbeef"}'
```

- **PASS:** HTTP 400, `pp_ResponseCode: "199"`, plus a `pp_SecureHash`.
- **FAIL:** HTTP 503 → the env vars didn't load.

**Watch a live payment:**

```bash
journalctl -u gamesbazaar-backend -f | grep -i jazzcash
```

Three independent paths resolve a payment — the IPN callback, the user returning to
`/wallet`, and the `gamesbazaar-reconcile-jazzcash` timer — so a missed IPN self-heals
within one timer interval. All three feed `apply_gateway_result`.

Status Inquiry waits a minimum of 10 minutes after initiation (`STATUS_INQUIRY_MIN_AGE`),
per JazzCash's 2026 guide — inquiring earlier risks a verdict on an in-flight transaction,
which `apply_gateway_result` would treat as final.

---

## If the server ever moves again

1. The new region must **not** be India (see trap 1). Run the WAF probe from the new box
   *before* cutting DNS over.
2. Update `DJANGO_ALLOWED_HOSTS` in the backend `.env` — it pins the server IP.
3. Return URL and IPN URL are domain-based, so **nothing needs re-registering** in the
   JazzCash merchant portal.
4. Tell JazzCash the new IP for their records — as courtesy, not as a whitelist request.

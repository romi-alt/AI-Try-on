# Deploying the ELEVARIQ Virtual Try on Mirror

This is the guide for putting the system on the internet for a real shop. It covers one shop with one or a few
mirrors. Nothing here has been run on a real server by the author: see "What has and has not been verified" at the
end before you rely on it.

## What runs where

```
 Shop                                   Internet                                     Your VPS (Docker Compose)
┌──────────────┐   https   ┌───────────────────────┐                     ┌─────────────────────────────────────┐
│ Mirror       │──────────▶│ Vercel: kiosk         │                     │ Caddy  :80/:443  (automatic HTTPS)  │
│ (Chrome      │           │  mirror.example.com   │                     │   │                                 │
│  kiosk mode) │───────────┼───────────────────────┼── https / wss ─────▶│   ▼                                 │
└──────────────┘           └───────────────────────┘                     │ api  (FastAPI)  ◀── worker (RQ)     │
┌──────────────┐           ┌───────────────────────┐                     │   │                  │              │
│ Staff / owner│──────────▶│ Vercel: admin         │── https (server) ──▶│   ▼                  ▼              │
│ browser      │           │  admin.example.com    │                     │ redis (internal, password)          │
└──────────────┘           └───────────────────────┘                     └───────┬─────────────────────────────┘
┌──────────────┐                                                                 │ TLS
│ Shopper's    │── https ─▶ kiosk /m/CODE (look + cart)                          ▼
│ phone        │                                          Managed Postgres + pgvector      Object storage (R2)
└──────────────┘                                          Try-on provider (FASHN or RunPod) · Sentry · PostHog
```

| Piece | Where | Why there |
|-------|-------|-----------|
| Kiosk app (`apps/kiosk`) | Vercel | static-ish Next.js app, global CDN, no server to run |
| Admin app (`apps/admin`) | Vercel | sign-in and a server-side proxy that holds the API's admin key |
| API, worker, Redis, Caddy | one VPS | long-lived processes and WebSockets; Redis must be close to the worker |
| Postgres | managed (Neon, Supabase, RDS, ...) | backups and upgrades are someone else's job; needs the **pgvector** extension |
| Photos, product images, looks | object storage (Cloudflare R2 or any S3-compatible bucket) | cheap, and the browser can upload to it directly |

## Before you start

- [ ] A **domain**, with three names ready: `api.` (the VPS), `mirror.` (Vercel kiosk), `admin.` (Vercel admin), plus
      `media.` for the bucket's public address if you use R2's custom domain.
- [ ] A **VPS**: 2 vCPU, 2 GB RAM (4 GB is comfortable), 20 GB disk, Ubuntu 24.04. Any provider.
- [ ] A **managed Postgres** with the `vector` extension available (Neon, Supabase and RDS all have it).
- [ ] An **object-storage bucket** (R2 recommended) and an access key for it.
- [ ] A **Vercel** account (two projects).
- [ ] A **try-on provider**: a FASHN API key, or your own CatVTON endpoint (see `services/catvton/README.md`).
- [ ] Optional: Sentry (errors), PostHog (usage events), a WhatsApp Cloud API number (staff alerts).

## 1. Postgres

1. Create a database and a user for the app. Copy the connection string and write it in SQLAlchemy form with TLS:
   `postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require`
2. Enable pgvector once, as the database owner: `CREATE EXTENSION IF NOT EXISTS vector;`
3. Turn on the provider's automatic backups / point-in-time recovery. Orders and the catalog live here and nowhere
   else. (Redis only holds the job queue; photos are deleted on purpose.)
4. If the provider has an IP allow-list, add the VPS's public IP.

## 2. Object storage (R2)

1. Create a bucket. Give it a **public address** for reading (an R2 custom domain such as `media.example.com`): product
   images and looks are served from it. Photos of shoppers are never public: the app hands out short-lived signed links.
2. Create an API token with read/write on that bucket. You get an access key id, a secret and an account endpoint
   (`https://<account>.r2.cloudflarestorage.com`).
3. **CORS** (the admin app uploads product images from the browser straight to the bucket):
   ```json
   [{"AllowedOrigins": ["https://admin.example.com"], "AllowedMethods": ["PUT", "GET"],
     "AllowedHeaders": ["Content-Type"], "MaxAgeSeconds": 3600}]
   ```
4. Lifecycle rules for photos are added by a command in step 4. They are a safety net; the API deletes photos itself.

## 3. The VPS

```bash
# as root, once
adduser deploy && usermod -aG sudo deploy         # then log in as `deploy` with your SSH key
# firewall: SSH, HTTP, HTTPS only. Nothing else is reachable, including Redis and the API.
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp && ufw enable
# security updates by themselves
apt-get update && apt-get install -y unattended-upgrades && dpkg-reconfigure -plow unattended-upgrades
# Docker (see https://docs.docker.com/engine/install/ubuntu/ for the current steps)
curl -fsSL https://get.docker.com | sh && usermod -aG docker deploy
```

Disable SSH password login (`PasswordAuthentication no` in `/etc/ssh/sshd_config`). Point `api.example.com`'s DNS
A record (and AAAA if you have IPv6) at the server. Docker publishes ports itself and bypasses `ufw` for them, which is
fine here because only Caddy publishes anything (80 and 443).

## 4. Configure and start the stack

```bash
git clone <your repository> elevariq && cd elevariq/deploy
cp .env.production.example .env.production
nano .env.production            # fill in every CHANGE_ME (generate secrets with: openssl rand -hex 24)
python3 preflight.py            # must say "preflight passed"
```

`preflight.py` refuses: placeholder or development secrets, short keys, `http://` or `localhost` browser origins, a
database connection without TLS, photo retention longer than one hour, public API docs, and missing provider keys. Fix
everything it lists.

```bash
./compose.sh build                              # builds the API and worker images (a few minutes)
./compose.sh run --rm migrate                   # creates the database tables
./compose.sh run --rm migrate python -m scripts.apply_lifecycle     # bucket safety-net rules for photos
./compose.sh up -d
./compose.sh ps                                 # api, worker, redis, caddy: all "healthy" after about a minute
curl -s https://api.example.com/health/ready    # {"status":"ok","checks":{...}}
```

`/health/ready` answers 503 when Postgres or Redis is down, and `"degraded"` (still 200) when storage or the try-on
worker is unavailable. Caddy fetches the HTTPS certificate on first start; if it cannot, check that the DNS record points
at this server and that ports 80 and 443 are open (`./compose.sh logs caddy`).

The optional **assets worker** (embeddings for recommendations, background removal for new product images) is heavy
(PyTorch, several GB). Run it with `./compose.sh --profile assets up -d assets-worker` on a machine with the RAM for it
(4 GB or more, free), or run it elsewhere against the same Redis and database.

## 5. Vercel: the kiosk and the admin

Create **two** projects from the same repository. For each: *Settings, General, Root Directory* = `apps/kiosk` or
`apps/admin`, and turn on **Include source files outside of the Root Directory** (the apps are npm workspaces and
install from the repository root). `vercel.json` in each folder sets the install and build commands.

**Kiosk project** (`mirror.example.com`), environment variables. These are baked in at build time, so redeploy after
changing one:

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | `https://api.example.com` |
| `NEXT_PUBLIC_PUBLIC_URL` | `https://mirror.example.com` (what the QR code points at; must be reachable from a phone) |
| `NEXT_PUBLIC_SHOP_NAME` | the shop's name, shown in the privacy notice |
| `NEXT_PUBLIC_PRIVACY_CONTACT` | an email or phone number for privacy questions |
| `NEXT_PUBLIC_PHOTO_RETENTION_MINUTES` | `60`: **must equal** the API's `CAPTURE_TTL_SECONDS` / `RESULT_TTL_SECONDS` in minutes |
| `NEXT_PUBLIC_TRYON_PROVIDER_NAME` | who renders the picture, as shoppers should read it (e.g. `FASHN`) |
| `NEXT_PUBLIC_SENTRY_DSN` | optional: the kiosk's Sentry DSN |
| `NEXT_PUBLIC_SENTRY_ENVIRONMENT` | `production` |

**Admin project** (`admin.example.com`), environment variables (server-side only; none reach the browser):

| Variable | Value |
|----------|-------|
| `API_URL` | `https://api.example.com` |
| `ADMIN_API_KEY` | the same value as `ADMIN_API_KEY` in `deploy/.env.production` |
| `NEXTAUTH_URL` | `https://admin.example.com` |
| `NEXTAUTH_SECRET` | `openssl rand -base64 32` |
| `ADMIN_USERS` | `email=password-hash` pairs; make a hash with `npm run hash-password -w @tryon/admin -- 'password'` |
| `NEXT_PUBLIC_SENTRY_DSN` | optional |

Then set the **function region** of the admin project near your VPS (Settings, Functions), and add the custom
domains. Finally put the two Vercel origins in the VPS's `API_CORS_ORIGINS` (`https://mirror.example.com,https://admin.example.com`,
exact, no trailing slash) and `./compose.sh up -d` again if you changed it. A browser calling the API from any other
origin is refused.

## 6. First-run checks

1. `https://api.example.com/health/ready` is `ok`. `https://api.example.com/docs` is a 404 (docs are off).
2. Open the admin, sign in, add a product with an image (this also proves the bucket's CORS rule), import a few more with
   the CSV page.
3. Open `https://mirror.example.com/try-on` on a normal computer, agree, choose an item, take a photo, and get a look.
4. On the look screen, **Add Selected to Cart** and scan the QR code with a phone: the page must open and show the cart.
5. Press **Request Outfit** and see it appear on `https://mirror.example.com/staff` (staff key from `STAFF_API_KEY`).
6. **Privacy check**: after the look, list the bucket (`captures/` and `results/`). An hour later both must be empty.
   Look at `./compose.sh logs api worker caddy`: no pictures, no `X-Amz-Signature`, no `/m/<code>` in full.
7. Pull the network cable on the mirror for a minute: it should show "We're reconnecting" and come back by itself.
8. Trigger a test error (Sentry's "send test event") and, if enabled, check that PostHog receives `session_start`.

## What is sent to monitoring

**Sentry** (errors; every service; off without a DSN): stack traces and messages only. Request bodies, cookies, addresses,
local variables and session replays are never sent, and every string is scrubbed of photos, signed links, keys and mobile
codes. **PostHog** (usage; the API and worker, server-side; off without a key): five events, each tied only to a random
per-visit id with no person profile and no location.

| Event | Sent when | Properties |
|-------|-----------|------------|
| `session_start` | a shopper agrees and a visit begins | none |
| `capture` | a photo is accepted | `width`, `height` |
| `tryon_done` | a look is finished | `product_count`, `recommended_count`, `render_seconds`, `total_seconds`, `provider` |
| `add_to_cart` | an item is added to the cart | `product_id`, `category`, `quantity`, `on_sale` |
| `request_outfit` | a shopper asks for an item | `product_id`, `category`, `has_size` |

Uptime monitors should poll `https://api.example.com/health/ready`, `https://mirror.example.com/api/health` and
`https://admin.example.com/api/health`.

## Privacy

The privacy notice on the mirror says photos and looks are deleted **within one hour**. Three settings must agree:
`CAPTURE_TTL_SECONDS` and `RESULT_TTL_SECONDS` on the VPS (both `3600` or less; `preflight.py` enforces it) and
`NEXT_PUBLIC_PHOTO_RETENTION_MINUTES` on the kiosk project. The API's sweeper deletes anything older every five
minutes; the bucket's lifecycle rules (step 4) are a day-long backstop if the API is down.

Where a shopper's picture goes: the mirror, your API and bucket, and the try-on provider (FASHN, or your RunPod endpoint).
Read the provider's terms for how long *they* keep inputs: it is outside this system. Logs never contain pictures, and
Caddy's access log truncates client addresses and masks `/m/CODE`.

**The wording of the notice is placeholder copy and needs a lawyer's review for your country** (especially anything about
facial images and children). So does the kiosk's consent text.

## Operating it

| Task | How |
|------|-----|
| Update | `git pull && cd deploy && export RELEASE=$(git rev-parse --short HEAD) && ./compose.sh build && ./compose.sh run --rm migrate && ./compose.sh up -d` (images are tagged with `RELEASE`, so the previous release stays on the server) |
| Roll back | `RELEASE=<previous commit> ./compose.sh up -d` (a migration is not undone: see below) |
| Logs | `./compose.sh logs -f api` (also `worker`, `caddy`, `redis`) |
| Restart one service | `./compose.sh restart worker` |
| More try-on capacity | `./compose.sh up -d --scale worker=2` (each holds one render at a time) |
| Rotate the admin key | change it in `deploy/.env.production` *and* the admin Vercel project, redeploy both |
| Rotate the staff key | `STAFF_API_KEY` in `deploy/.env.production`, `./compose.sh up -d`, tell staff |
| Backups | Postgres: the provider's PITR. Product images: the bucket (turn on versioning). Redis: nothing to back up |

Migrations only move forward. Before a release that adds one, take a manual Postgres backup/branch. To undo one:
`./compose.sh run --rm migrate alembic downgrade -1` (read the migration first; some drop data).

## Known limits you should decide on

- **Shared keys.** The API's admin and staff endpoints use shared secrets (`ADMIN_API_KEY`, `STAFF_API_KEY`). The admin app has
  real sign-in and keeps the admin key on its server, but the API itself is on the internet, so those keys are the only
  gate on it: keep them long, and rotate them if anyone who knew them leaves. Wrong keys lock an address out of the API
  for a while.
- **Admin sign-in rate limit is in memory.** On Vercel each server instance has its own counter, so it slows guessing but
  does not cap it. Add a Vercel Firewall rate-limit rule on `POST /api/auth/callback/credentials` for a real limit.
- **One VPS.** If it goes down the mirrors cannot make looks until it is back (the kiosk shows a reconnecting screen). There
  is no failover. Docker restarts crashed containers, and the host restarts after a reboot (`restart: unless-stopped`).
- **Payments are a stub** that approves everything: do not take real money until a real provider is written.
- **Rate limits** are per shopper session and per address (see `services/api/app/core/ratelimit.py`). If several mirrors
  share one shop address and hit limits, raise `RATE_LIMIT_SCALE`.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| Caddy cannot get a certificate | DNS does not point here yet, or ports 80/443 are blocked (`./compose.sh logs caddy`) |
| Kiosk says it cannot reach the server; browser console shows a CORS error | `API_CORS_ORIGINS` lacks the exact origin of the kiosk or admin (https, no trailing slash) |
| `/health/ready` is `down` | Postgres or Redis unreachable: check `DATABASE_URL` (TLS, allow-list) and `./compose.sh ps` |
| `/health/ready` is `degraded`, worker error | the worker is not running or cannot reach Redis/Postgres: `./compose.sh logs worker` |
| Looks never finish | worker down, or the provider key is wrong (the worker log names the cause); the kiosk offers Try again after a minute |
| Admin product upload fails | the bucket's CORS rule does not allow `PUT` from the admin origin |
| The QR code opens a page that does not load | `NEXT_PUBLIC_PUBLIC_URL` points at localhost or a name a phone cannot reach |
| Everyone gets `429` | the shop address is shared by many mirrors, or a client is looping: see `rate_limited` in the API log |
| Photos still in the bucket after an hour | `CAPTURE_CLEANUP_ENABLED` is off or the API is down: check `./compose.sh logs api` for `capture_sweep_failed` |

## What has and has not been verified

**Verified** (automated tests and browser runs, against a real Postgres, Redis and an S3-compatible server): the rate
limiter, input validation, log and error-report scrubbing, the readiness and worker health checks, the privacy retention
sweeper, the five analytics events (against a fake PostHog), Sentry's scrubbing in a real browser against a fake Sentry
server, the kiosk's offline behaviour (API outage, connection loss during a render, a reload with no network),
the privacy notice, `deploy/preflight.py`, the kiosk launcher and policy installer in dry-run mode, a clean non-editable
install of the API and worker packages, and `docker compose config` on the production compose file.

**Not verified** (it needs a server, accounts or hardware that were not available):
- **Nothing was deployed.** The production Docker images were never built (there is no Docker daemon where this was written),
  the stack was never started on a VPS, and Vercel was never used.
- **The Caddyfile was never validated by Caddy** (the binary could not be run). Run
  `docker compose run --rm caddy caddy validate --config /etc/caddy/Caddyfile` once; the access-log filter syntax is the
  part most likely to need a tweak.
- Certificate issuance, WebSockets through Caddy, and the real client address reaching the rate limiter through
  `X-Forwarded-For`.
- Vercel monorepo settings (the exact "include files outside the root" wording changes), the security headers in
  production, and the service worker on Vercel's CDN.
- Real Sentry and PostHog projects (only fakes were used), and real WhatsApp.
- The kiosk on a real screen, webcam and Chrome install: see `docs/KIOSK_SETUP.md`.

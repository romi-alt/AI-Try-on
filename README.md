# ELEVARIQ Virtual Try on Mirror

The ELEVARIQ Virtual Try on Mirror is an AI virtual try-on mirror for a clothing shop. A portrait touch screen with a
webcam acts as the mirror: the shopper picks items, the kiosk guides them into position and takes a photo, and a
worker renders the items onto them. They can then add pieces to a cart, send the look and cart to their phone with a
QR code, or ask a team member to bring an item in their size.

```
apps/kiosk       Next.js 14 (App Router, TS, Tailwind, Zustand, TanStack Query) — the mirror UI (1080x1920),
                 plus the staff page (/staff) and the shopper's mobile page (/m/CODE)
apps/admin       Next.js 14 + NextAuth — products, CSV import, image processing, analytics, orders, jobs
services/api     FastAPI — catalog, recommendations, sessions, cart, checkout, capture, try-on jobs, staff requests
services/worker  Python — RQ workers: try-on rendering (mock, FASHN, CatVTON) and image assets (embeddings, cutouts)
services/catvton CatVTON as a RunPod serverless GPU worker (Docker image, handler, deploy and benchmark tooling)
infra            docker-compose: Postgres + pgvector, Redis, MinIO (local R2)
```

## How a try-on flows

1. Kiosk starts a **session** (`POST /sessions`, only accepted with `consent_given: true`) and loads the catalog (`GET /catalog`).
2. The shopper taps *Try it on*. The kiosk uploads a webcam frame to `POST /capture`. The API checks it
   (JPEG or WebP, max 5 MB, portrait, at least 768px tall), strips EXIF, stores it as WebP under
   `captures/{session_id}/{uuid}.webp` and returns the key. Captures are deleted after an hour.
3. The kiosk calls `POST /tryon` with `session_id`, `capture_key` and `product_ids`. The API inserts a
   `queued` job in Postgres, pushes it onto an **RQ** queue in Redis, and returns the `job_id` immediately.
4. The **worker** picks the job up and runs it through the configured provider (`TRYON_PROVIDER`: `mock`
   `fashn` or `catvton`). After every progress step it records the latest state in the Redis hash `job:{id}` and
   publishes `{job, status, pct}` to the channel `session:{session_id}:job`, in one transaction.
5. When rendering finishes the worker uploads the result to object storage and publishes
   `{job, status: "done", pct: 100, url}`; on any failure it publishes `{job, status: "failed", pct, error}`
   with a message that is safe to show the shopper.
6. The kiosk follows along on **`WS /ws?session={id}`**, which forwards everything published for its session,
   with a heartbeat every 25 seconds. After a reconnect, or if WebSockets are unavailable, it reads
   **`GET /jobs/{id}`** for the current state. Details and a client recipe are in `services/api/README.md`.

Products carry a 512-d pgvector embedding; `GET /products/{id}/similar` returns nearest neighbours.

### Try-on providers

| `TRYON_PROVIDER` | What it does |
|------------------|--------------|
| `mock` (default) | Offline. Waits `MOCK_DURATION_SECONDS` (8) while reporting progress, then returns the photo with the garments and a "MOCK TRY-ON" banner. `MOCK_FAIL=true` forces failures. |
| `fashn`          | Calls the hosted [FASHN](https://docs.fashn.ai) API. Needs `FASHN_API_KEY`. Tops, bottoms and dresses only; outfits are applied one garment at a time. |
| `catvton`        | [CatVTON](https://github.com/Zheng-Chong/CatVTON) running on your own **RunPod serverless** endpoint (scale to zero), called over HTTPS. Needs `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID`. Tops, bottoms and dresses; the whole outfit is one request; progress comes from the diffusion steps. Image, handler, deploy script and benchmark are in [`services/catvton`](services/catvton/README.md). **The GPU side has not been built or run: see "Verification status" below.** |

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2)
- Node 20+ (only if you want to run the Next.js apps natively)
- Python 3.11+ (only if you want to run the Python services natively)

## Quick start

```bash
make env        # copies every .env.example -> .env / .env.local
make dev        # builds and starts the full stack (first run takes a few minutes)
```

In a second terminal, once `api` is up:

```bash
make migrate    # alembic upgrade head
make seed       # 20 demo products + placeholder images/masks in the bucket
make lifecycle  # optional: day-long expiry rule on captures/ (the API sweeper enforces the hour)
```

Then open:

| What            | URL                          |
|-----------------|------------------------------|
| Kiosk           | http://localhost:3000        |
| Staff page      | http://localhost:3000/staff (staff key, dev default `dev-staff-key`) |
| Admin           | http://localhost:3001 (dev sign-in `admin@example.com` / `dev-admin-password`) |
| API docs        | http://localhost:8000/docs   |
| MinIO console   | http://localhost:9001 (creds in `.env`) |

The browser will ask for camera permission once the shopper agrees on the consent screen.

## The kiosk

`apps/kiosk` is a fullscreen **1080x1920 portrait** touch UI in a dark glass style (every tappable target is at least
64 px). Flow:

1. **Attract screen.** After 60 seconds without input (45 s, then a 15 s "Are you still there?" countdown) the kiosk
   returns to the attract screen and **resets the session**: the camera and live connection close and the last
   shopper's outfit, photo and cart are forgotten. Touching the screen starts again. The timer is paused while a photo
   is being taken or a look is rendering, and uses the real clock.
2. **Shop.** Top tabs (Clothing, Accessories, Shoes, Bags, Flat 50% Off, New Arrivals), a 3-column product grid, a left
   sidebar (Shop, Scanner, Cart, Help, Settings) and a **Selected items** tray at the top. Tapping a product opens a
   detail panel with size and colour selectors. Prices are in PKR, with the regular price struck through on sale items.
   Data comes from the API through TanStack Query.
3. **Consent.** Nothing is captured and the camera stays off until the shopper agrees (the consent text is placeholder
   copy and needs review before real use).
4. **Capture.** `getUserMedia` asks for 1920x1080 and shows a mirrored preview. **MediaPipe Pose Landmarker** (WASM, in a
   Web Worker) looks at every frame and the screen says *Step back* until head and ankles are in view, *Center
   yourself* when off-centre, *Hold still* when steady. After one second of steadiness a 3-2-1 *Strike a pose* countdown
   runs; the **sharpest of the last 5 frames** (Laplacian variance) is cropped to 3:4 and sent to `POST /capture`. If
   pose guidance cannot load there is a *Take my photo* button that runs the same countdown by hand. Cancel at any time
   releases the camera.
5. **Progress.** `POST /tryon`, then a circular progress ring with the percentage and *Almost there...* over a blurred
   copy of the shopper's own photo. The socket reconnects with exponential backoff; while it is down the kiosk polls
   `GET /jobs/{id}` every 2 s. After 60 s *Try again* appears (the job keeps running meanwhile).
6. **Result.** The finished look is preloaded and fades in only once fully loaded. A *Look 1 / Look 2* switcher keeps
   every look from the visit. The side panel *Add to cart?* has a checkbox, size and colour per item, plus
   **Complete your look** (one best match for each missing top / bottom / shoes / bag) and **More styles** (nearest
   neighbours in the same category), each with a one-tap *Try on*. Buttons: **Add Selected to Cart**, **Request Outfit**,
   **Back to Shop**.
7. **Cart and checkout.** Quantities, removal, and *Place order* (pay at the counter, six-character pickup code, idempotent).

**Add Selected to Cart** saves the items and shows a **QR code** to `/m/{short_code}` on the shopper's phone. **Request
Outfit** asks staff to bring an item in a size.

Configuration is in `apps/kiosk/.env.example`. `NEXT_PUBLIC_*` values are read at build time, so rebuild after changing
them. The build downloads the MediaPipe pose model and copies its WASM into `public/mediapipe` (`npm run pose-assets`,
needs network). **Set `NEXT_PUBLIC_PUBLIC_URL` to an address a phone can reach**, or the QR code will point at the kiosk's
own `localhost`.

### Recommendations

Products carry a 512-d **FashionCLIP** embedding (computed by the assets worker: `make embed` for products without one;
admin buttons recompute some or all). `GET /recommend?product_ids=...` returns:

- **More styles**: nearest neighbours of the selected items in the same category, by pgvector cosine distance.
- **Complete your look**: for each missing category among top, bottom, shoes and bag (a dress covers top and bottom), the
  best product that passes simple rules: colour harmony with everything selected (neutrals go with anything, then tonal,
  analogous, complementary; the awkward middle of the wheel is out) and a price within 4x of the selection's average;
  candidates are ranked by embedding similarity. Without embeddings it falls back to the newest in the category.

### The mobile page and the staff page

Both live in the kiosk app and are separate from the mirror UI.

- **`/m/CODE`** (the QR code) is a phone page: the shopper's look, their cart, and a **Pay** button that goes through a
  payment provider interface (`services/api/app/services/payments.py`; only a **stub** is included, it approves every
  payment). The code is random, expires after 24 hours (`SHARE_LINK_TTL_SECONDS`) and only reaches that session's look
  and cart. A declined payment cancels the order, restores stock and leaves the cart as it was; retries after a lost
  connection reuse an idempotency key so nobody is charged twice. `/m` lets a phone type the code if it cannot scan.
- **`/staff`** is for the shop floor. Sign in with the staff key (`STAFF_API_KEY`). It lists open **Request Outfit**
  requests (product, size, colour, which mirror session, how long ago) and updates **live** over `WS /ws/staff` on every
  staff screen: *Bringing it* shows "On the way" everywhere, *Done* removes the request everywhere. If the socket drops it
  reconnects and re-reads the list.
- **Notifications.** Creating a request also notifies staff through a pluggable notifier (`NOTIFIER`): `console` for
  development, or `whatsapp` for the WhatsApp Cloud API (`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TO`; set
  `WHATSAPP_TEMPLATE_NAME` to send an approved template, which WhatsApp requires outside its 24-hour window). The WhatsApp
  notifier is tested against a fake server only.

## The admin app

`apps/admin` (http://localhost:3001) is for the shop's staff and owners.

**Sign-in.** NextAuth with an email and password. Who may sign in is the `ADMIN_USERS` allow-list (`email=password hash`,
hashes made with `npm run hash-password -w @tryon/admin -- 'password'`; scrypt, nothing extra to install). Every page is
protected, failed sign-ins are rate limited, and the session is an HttpOnly cookie. *This is email and password rather
than an emailed magic link, which would need an SMTP service; NextAuth's email provider can replace it if you have one.*
The browser never sees the API's admin key: it calls the app's own `/api/proxy`, which checks the session and adds
`X-Admin-Key` on the server (`ADMIN_API_KEY`, `API_URL`).

- **Overview.** Today's counters and the queue depth.
- **Products.** Search and filters, stock edited in place, add/edit with SKU, price, sale price, sizes, colours and an
  image uploaded straight to the bucket (presigned PUT; the bucket must allow CORS PUT from the admin origin). **Remove
  background** queues a job on the assets worker: **rembg** cuts the garment out, **SAM 2** refines the outline into a
  garment mask, the original upload is kept, and the new embedding is stored before the product shows *Cutout ready*.
  Status (queued, processing, ready, failed with the reason) updates live. **Re-embed**, **Embed missing** and **Re-embed
  all** recompute FashionCLIP embeddings.
- **Import CSV.** Upload a CSV, *Check file* (a dry run that lists every problem with its line number), then *Import*.
  Rows with an existing SKU update that product (empty cells keep the current value, `none` removes a sale price); other
  rows create one. It is all or nothing, so a bad row never leaves half a file imported. Columns:
  `sku,name,category,price_pkr,sale_price_pkr,sizes,colors,stock,image_url` (sizes `S|M|L`, colours `Name:#hex|...`). A
  template can be downloaded from the page.
- **Analytics.** Try-ons per product, the **try-on to cart rate**, and the **top recommended pairings** (suggestions
  shoppers added to a look, with the item they were added to), for the last 7, 30 or 90 days. A try-on is a finished look;
  an item counts as added when the same session put it in the cart (or ordered it) at or after the look. Definitions are
  in `services/api/app/api/analytics.py`.
- **Orders**, **Sessions**, **Try-on jobs**: as before (mark orders collected or cancelled, watch jobs).

Unit tests (`make test-admin`) cover sign-in, the proxy, the form logic, the CSV helpers and the API client.

## Going to production

- **[DEPLOY.md](DEPLOY.md)**: kiosk and admin on Vercel; API, worker, Redis and Caddy (automatic HTTPS) on a VPS with Docker
  Compose; Postgres managed. Includes a `preflight.py` that refuses dev keys, `http` origins and retention longer than the
  privacy promise, plus operations, monitoring and a list of what has not been verified.
- **[docs/KIOSK_SETUP.md](docs/KIOSK_SETUP.md)**: the mirror computer: Chrome kiosk mode, autostart, camera permission by
  policy, portrait screen and touch, power and sleep, and what happens when the internet drops.

What production adds to the code:

- **Rate limiting** per session (capture, try-on, cart, share, Request Outfit, checkout) and per address (starting sessions,
  guessing mobile-page codes, wrong admin/staff keys, WebSocket connects). `429` with `Retry-After`; Redis-backed; fails open.
- **Input validation** on every public input: bounded lists and strings, no control characters in names and labels, a body-size
  cap, strict consent (`true` only), and options that must exist on the product.
- **Privacy**: a photo and its finished look are deleted within one hour (`CAPTURE_TTL_SECONDS`, `RESULT_TTL_SECONDS`), logs and
  error reports are scrubbed of pictures, signed links and keys, and a **Privacy** badge on every mirror screen opens the full
  notice (also at `/privacy`). The notice wording is placeholder copy that needs legal review.
- **Observability**: Sentry in all four services (off without a DSN; no replay, no personal data), five anonymous PostHog events
  sent from the server (`session_start`, `capture`, `tryon_done`, `add_to_cart`, `request_outfit`), `/health` (liveness) and
  `/health/ready` (Postgres and Redis required, storage and worker reported), worker `python -m worker.healthcheck`, and
  `/api/health` on the kiosk and admin.
- **Offline**: the mirror checks its server and, if it cannot reach it, shows a "reconnecting" cover (a banner during capture and
  rendering), recovers by itself, and can still reload with no connection thanks to a service worker.

## Make targets

| Target            | What it does                                                  |
|-------------------|---------------------------------------------------------------|
| `make dev`        | Start everything with hot reload                              |
| `make dev-infra`  | Start only Postgres, Redis, MinIO (run apps natively)         |
| `make migrate`    | Run Alembic migrations                                        |
| `make migration m="..."` | Autogenerate a migration from model changes            |
| `make seed`       | Seed 20 demo products (idempotent)                            |
| `make lifecycle`  | Add the bucket lifecycle backstop for `captures/`             |
| `make test`       | Run API and worker tests                                      |
| `make embed`      | Compute embeddings for products that have none                |
| `make test-catvton` | Run the CatVTON GPU service's unit tests (no GPU needed)    |
| `make benchmark-fake` | Try the latency/cost benchmark against a fake RunPod       |
| `make test-kiosk` | Run the kiosk's unit tests (host Node, no services)           |
| `make test-admin` | Run the admin app's unit tests (host Node, no services)       |
| `make test-deploy` | Test the deploy helpers: preflight, kiosk launcher, policy installer |
| `make preflight`  | Check `deploy/.env.production` before deploying               |
| `make lint`       | ESLint + Ruff across all packages                             |
| `make logs` / `make ps` | Tail logs / list services                               |
| `make psql`       | psql shell into the dev DB                                    |
| `make down`       | Stop, keep data                                               |
| `make clean`      | Stop and delete volumes                                       |

## Running pieces natively

Start infra only, then run whichever service you are iterating on:

```bash
make dev-infra

# API
cd services/api && python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]" && alembic upgrade head && uvicorn app.main:app --reload

# Worker
cd services/worker && python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]" && python -m worker.main

# Kiosk / admin
npm install
npm run dev:kiosk     # http://localhost:3000
npm run dev:admin     # http://localhost:3001
```

Each package has its own `.env.example` with localhost defaults for this mode.

## Configuration & secrets

- Every `.env.example` is safe to commit; copy it and edit the copy. `.env*` files
  are git-ignored except the examples. **Never commit a real key.**
- Defaults are dev-only (`minioadmin`, `dev-admin-key`, `dev-staff-key`, the `admin@example.com` /
  `dev-admin-password` sign-in, `NEXTAUTH_SECRET`). Rotate everything before any shared deployment.
- The API's admin endpoints use a shared `X-Admin-Key` and the staff endpoints a shared `X-Staff-Key`. The admin *app* has
  real sign-in and keeps the admin key on its server; the keys themselves are still shared secrets between servers.
- Switching from MinIO to Cloudflare R2 is env-only; see `infra/README.md`.
- Real try-on: `TRYON_PROVIDER=fashn` with `FASHN_API_KEY`, or `TRYON_PROVIDER=catvton` with `RUNPOD_API_KEY` and
  `RUNPOD_ENDPOINT_ID` (see `services/catvton/README.md`). The provider interface is in
  `services/worker/worker/providers/base.py`.
- Production settings (`RATE_LIMIT_*`, `RESULT_TTL_SECONDS`, `API_DOCS_ENABLED`, `SENTRY_*`, `POSTHOG_*`, the kiosk's `NEXT_PUBLIC_SHOP_NAME`,
  `NEXT_PUBLIC_PHOTO_RETENTION_MINUTES`, `NEXT_PUBLIC_SENTRY_*`) are in each package's `.env.example` and `deploy/.env.production.example`.
- Earlier settings: `NEXT_PUBLIC_PUBLIC_URL`, `NEXT_PUBLIC_POSE_DELEGATE`, `NEXT_PUBLIC_TRYON_SLOW_SECONDS`
  (kiosk); `STAFF_API_KEY`, `NOTIFIER`, `WHATSAPP_*`, `PAYMENT_PROVIDER`, `STUB_PAYMENT_OUTCOME`, `SHARE_LINK_TTL_SECONDS`,
  `ASSETS_QUEUE_NAME` (API); `WORKER_QUEUES`, `SAM2_CHECKPOINT`, `REMBG_MODEL`, `FASHION_CLIP_MODEL`, `RUNPOD_*`,
  `CATVTON_*` (worker); `NEXTAUTH_URL`, `NEXTAUTH_SECRET`, `ADMIN_USERS`, `ADMIN_API_KEY`, `API_URL` (admin).

## Verification status

What the automated tests and the browser runs in this repository cover, and what nobody has been able to check:

**Verified**: the API (pytest against Postgres, Redis and a fake S3), the worker (including FashionCLIP embeddings and
rembg + SAM 2 garment cutouts with the real models), the kiosk and admin (unit tests, plus real Chromium runs with a fake
camera video: pose guidance with the real MediaPipe model, the countdown and sharpest-frame capture, progress, result,
recommendations, QR, Request Outfit, the staff page across two screens, the phone page including a declined payment, and
the admin sign-in, product, image-processing, CSV and analytics flows), and the CatVTON client, handler, deploy script
and benchmark against fakes.

**Not verified** (it needs hardware or accounts that were not available): the CatVTON Docker image (never built), CatVTON
itself on a GPU (never run), the RunPod endpoint (never deployed, so no real latency or cost figures exist; the benchmark
only prints simulated numbers with `--fake`), RunPod's exact progress and REST behaviour, the WhatsApp Cloud API (tested
against a fake server), the payment provider (stub only), a real phone scanning the QR code, a physical webcam and
touch screen, GPU pose guidance, and Chromium only (no other browsers). See `services/catvton/README.md` for details.

## Repo layout

```
.
├── apps/
│   ├── kiosk/          Next.js kiosk (shop, capture, progress, result, recommendations, cart) + /staff + /m/CODE
│   └── admin/          Next.js admin (sign-in, products, CSV import, image processing, analytics, orders, jobs)
├── services/
│   ├── api/            FastAPI + SQLAlchemy + Alembic + pgvector
│   ├── worker/         RQ workers: try-on providers (mock, fashn, catvton), embeddings, background removal
│   └── catvton/        CatVTON RunPod serverless image + handler + deploy script (GPU; see its README)
├── deploy/             Production: compose file, Caddyfile, env example, preflight check, kiosk launcher and Chrome policy
├── docs/               KIOSK_SETUP.md
├── infra/
│   ├── docker-compose.yml
│   └── postgres/init.sql   (CREATE EXTENSION vector)
├── Makefile
├── package.json        npm workspaces for apps/*
└── .env.example        compose-level variables
```

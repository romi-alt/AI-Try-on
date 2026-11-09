# AI Try-On Mirror

An AI virtual try-on mirror. A laptop webcam acts as the mirror: the shopper picks a
outfit, the kiosk captures a frame, and a worker renders the items onto them.

```
apps/kiosk      Next.js 14 (App Router, TS, Tailwind, Zustand) — the mirror UI
apps/admin      Next.js 14 — catalog, sessions and job monitoring
services/api    FastAPI — catalog, sessions, cart, capture upload, try-on jobs
services/worker Python — RQ worker that renders try-ons
infra           docker-compose: Postgres + pgvector, Redis, MinIO (local R2)
```

## How a try-on flows

1. Kiosk starts a **session** (`POST /sessions`, only accepted with `consent_given: true`) and loads the catalog (`GET /catalog`).
2. The shopper taps *Try it on*. The kiosk uploads a webcam frame to `POST /capture`. The API checks it
   (JPEG or WebP, max 5 MB, portrait, at least 768px tall), strips EXIF, stores it as WebP under
   `captures/{session_id}/{uuid}.webp` and returns the key. Captures are deleted after an hour.
3. The kiosk calls `POST /tryon` with `session_id`, `capture_key` and `product_ids`. The API inserts a
   `queued` job in Postgres, pushes it onto an **RQ** queue in Redis, and returns the `job_id` immediately.
4. The **worker** picks the job up and runs it through the configured provider (`TRYON_PROVIDER`: `mock`
   or `fashn`). After every progress step it records the latest state in the Redis hash `job:{id}` and
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
| Admin           | http://localhost:3001        |
| API docs        | http://localhost:8000/docs   |
| MinIO console   | http://localhost:9001 (creds in `.env`) |

The browser will ask for camera permission once the shopper agrees on the consent screen.

## The kiosk

`apps/kiosk` is what the shopper uses, on a laptop-sized screen:

1. **Consent.** Nothing is captured and the camera stays off until the shopper agrees. Agreeing starts the session.
   The consent text is placeholder copy and needs review before real use.
2. **Choose.** The catalog (`GET /catalog`) with category tabs, an *On sale* toggle, search and *Show more* paging.
   Up to 5 items can be picked as one outfit, and the outfit survives filter changes.
3. **Try on.** A 3-2-1 countdown, then one frame is cropped to a 3:4 portrait (a landscape webcam would be
   refused by the API) and sent to `POST /capture`, then `POST /tryon`.
4. **Watch.** Progress comes over a WebSocket held open for the whole session. It reconnects with backoff,
   replaces a connection that has gone silent, and polls `GET /jobs/{id}` every 2 seconds while the socket is
   down, so a look still finishes if WebSockets are blocked. Failures show the worker's readable message.
5. **Result.** The result image, with a size and colour choice per item and *Add to cart*. The cart drawer shows
   the API's totals. The camera is switched off while the result is shown.

Leaving the page (Exit) ends the session and closes the live connection. There is no idle timeout yet, and the
cart is add-only because the API has no remove endpoint.

Configuration is in `apps/kiosk/.env.example` (`NEXT_PUBLIC_API_URL`, optional `NEXT_PUBLIC_WS_URL`). These are
read at build time, so rebuild after changing them. Unit tests (`make test-kiosk`) cover the live-update
follower, the store's async flow, the API client and the photo crop; they need no services.

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
| `make test-kiosk` | Run the kiosk's unit tests (host Node, no services)           |
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
  are git-ignored except the examples.
- Defaults are dev-only (`minioadmin`, `dev-admin-key`, …). Rotate everything before
  any shared deployment.
- Admin endpoints use a shared `X-Admin-Key` header for now. Replace
  `services/api/app/core/auth.py` with a real identity provider before going public.
- Switching from MinIO to Cloudflare R2 is env-only; see `infra/README.md`.
- Real try-on: set `TRYON_PROVIDER=fashn` and `FASHN_API_KEY` in the root `.env`. The provider interface is
  in `services/worker/worker/providers/base.py`.

## Repo layout

```
.
├── apps/
│   ├── kiosk/          Next.js kiosk (consent, catalog, webcam mirror, live progress, outfit options, cart)
│   └── admin/          Next.js admin (garments CRUD, sessions, jobs, stats)
├── services/
│   ├── api/            FastAPI + SQLAlchemy + Alembic + pgvector
│   └── worker/         RQ worker + try-on providers (mock, fashn)
├── infra/
│   ├── docker-compose.yml
│   └── postgres/init.sql   (CREATE EXTENSION vector)
├── Makefile
├── package.json        npm workspaces for apps/*
└── .env.example        compose-level variables
```

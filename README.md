# AI Try-On Mirror

An AI virtual try-on mirror. A laptop webcam acts as the mirror: the shopper picks a
garment, the kiosk captures a frame, and a worker renders the garment onto them.

```
apps/kiosk      Next.js 14 (App Router, TS, Tailwind, Zustand) — the mirror UI
apps/admin      Next.js 14 — catalog, sessions and job monitoring
services/api    FastAPI — catalog, sessions, presigned uploads, try-on jobs
services/worker Python — consumes the Redis queue and renders try-ons
infra           docker-compose: Postgres + pgvector, Redis, MinIO (local R2)
```

## How a try-on flows

1. Kiosk starts a **session** (`POST /sessions`) and loads active **garments**.
2. Shopper picks a garment and taps *Try it on*. The kiosk grabs a webcam frame.
3. Kiosk asks the API for a **presigned PUT URL** and uploads the JPEG straight to
   object storage (MinIO locally, Cloudflare R2 in prod). Image bytes never pass
   through the API.
4. Kiosk creates a **try-on job** (`POST /tryon`). The API records it in Postgres and
   pushes the job id onto a Redis list.
5. The **worker** pops the job, downloads capture + garment, runs the configured
   provider (`stub` by default, `replicate` for a hosted VTON model), writes the
   result image to storage and marks the job done.
6. Kiosk polls `GET /tryon/{id}` and shows the result.

Garments carry a 512-d pgvector embedding; `GET /garments/{id}/similar` returns
nearest neighbours for "you might also like" shelves.

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
make seed       # 10 demo garments + placeholder images in the bucket
```

Then open:

| What            | URL                          |
|-----------------|------------------------------|
| Kiosk           | http://localhost:3000        |
| Admin           | http://localhost:3001        |
| API docs        | http://localhost:8000/docs   |
| MinIO console   | http://localhost:9001 (creds in `.env`) |

The browser will ask for camera permission on the kiosk's try-on screen.

## Make targets

| Target            | What it does                                                  |
|-------------------|---------------------------------------------------------------|
| `make dev`        | Start everything with hot reload                              |
| `make dev-infra`  | Start only Postgres, Redis, MinIO (run apps natively)         |
| `make migrate`    | Run Alembic migrations                                        |
| `make migration m="..."` | Autogenerate a migration from model changes            |
| `make seed`       | Seed demo garments                                            |
| `make test`       | Run API tests                                                 |
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
- Real try-on models: set `TRYON_PROVIDER=replicate` and the Replicate token in
  `services/worker/.env`. The worker's provider interface is in
  `services/worker/worker/providers/base.py`.

## Repo layout

```
.
├── apps/
│   ├── kiosk/          Next.js kiosk (webcam mirror, garment carousel, result view)
│   └── admin/          Next.js admin (garments CRUD, sessions, jobs, stats)
├── services/
│   ├── api/            FastAPI + SQLAlchemy + Alembic + pgvector
│   └── worker/         Redis consumer + try-on providers
├── infra/
│   ├── docker-compose.yml
│   └── postgres/init.sql   (CREATE EXTENSION vector)
├── Makefile
├── package.json        npm workspaces for apps/*
└── .env.example        compose-level variables
```

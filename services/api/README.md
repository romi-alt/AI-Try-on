# services/api

FastAPI backend. Owns the catalog, kiosk sessions, presigned uploads and try-on job records.

## Endpoints

| Method | Path                         | Auth   | Purpose                                      |
|--------|------------------------------|--------|----------------------------------------------|
| GET    | `/health`, `/health/ready`   | –      | Liveness / readiness (checks Postgres+Redis) |
| GET    | `/products`                  | –      | Catalog (`?category=`, `?in_stock=true`)     |
| GET    | `/products/{id}`             | –      | One product                                  |
| GET    | `/products/{id}/similar`     | –      | pgvector nearest neighbours                  |
| POST/PATCH/DELETE | `/products…`      | admin  | Catalog management                           |
| POST   | `/sessions`                  | –      | Start a session (`consent_given`)            |
| GET    | `/sessions`                  | admin  | Sessions with try-on counts                  |
| POST   | `/uploads/presign`           | –      | Presigned PUT URL for a capture/garment image|
| POST   | `/tryon`                     | –      | Enqueue a job for 1–5 `product_ids` (202)    |
| GET    | `/tryon/{id}`                | –      | Poll job status / result URL                 |
| GET    | `/tryon`                     | admin  | Recent jobs                                  |
| GET    | `/admin/stats`               | admin  | Dashboard counters                           |

## Data model

Migrations live in `alembic/versions/` (`make migrate`; `make migration m="..."` autogenerates).

| Table        | Notes                                                                                   |
|--------------|-----------------------------------------------------------------------------------------|
| `products`   | `category` enum (top, bottom, dress, shoes, bag, accessory); `price_pkr` / `sale_price_pkr` in whole rupees (sale never above price); `sizes`, `colors` jsonb; `stock >= 0`; `garment_image_url`, `garment_mask_url`; `embedding vector(512)` with an HNSW cosine index |
| `sessions`   | `started_at`, `consent_given`                                                           |
| `tryon_jobs` | `session_id`, `product_ids uuid[]` (at least one, not a FK so history survives catalog edits), `status` enum, `progress` 0-100, `person_image_key`, `result_url`, `error`, `created_at`, `updated_at` |
| `carts`      | one per session                                                                         |
| `cart_items` | `cart_id`, `product_id` (RESTRICT delete), optional `size` / `color`, `quantity > 0`    |

Seed: `make seed` creates 20 products with generated placeholder images and masks. Pass
`--no-upload` (`python -m scripts.seed --no-upload`) to write DB rows without touching the bucket.
`pytest` includes constraint tests that run against a migrated Postgres and skip if none is reachable.

Admin auth is a dev-only shared header `X-Admin-Key` (see `.env.example`). Swap `app/core/auth.py`
for a real identity provider before going public.

## Run natively

```bash
cd services/api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # points at localhost infra from `make dev-infra`
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

Interactive docs: http://localhost:8000/docs

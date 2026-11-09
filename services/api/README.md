# services/api

FastAPI backend. Owns the catalog, kiosk sessions, presigned uploads and try-on job records.

## Endpoints

| Method | Path                         | Auth   | Purpose                                      |
|--------|------------------------------|--------|----------------------------------------------|
| GET    | `/health`, `/health/ready`   | –      | Liveness / readiness (checks Postgres+Redis) |
| GET    | `/catalog`                   | –      | Paged catalog: `category`, `on_sale`, `search`, `page`, `page_size` (max 100) |
| GET    | `/products/{id}`             | –      | One product                                  |
| GET    | `/products/{id}/similar`     | –      | pgvector nearest neighbours                  |
| POST/PATCH/DELETE | `/products…`      | admin  | Catalog management                           |
| POST   | `/sessions`                  | –      | Start a session; 422 unless `consent_given` is true |
| GET    | `/sessions`                  | admin  | Sessions with try-on counts                  |
| POST   | `/cart/add`                  | –      | Add a product (size/color/quantity) to the session's cart; returns the cart |
| GET    | `/cart/{session_id}`         | –      | The session's cart with prices and subtotal  |
| POST   | `/uploads/presign`           | –      | Presigned PUT URL for a capture/garment image|
| POST   | `/tryon`                     | –      | Enqueue a job for 1–5 `product_ids` (202)    |
| GET    | `/tryon/{id}`                | –      | Poll job status / result URL                 |
| GET    | `/tryon`                     | admin  | Recent jobs                                  |
| GET    | `/admin/stats`               | admin  | Dashboard counters                           |

## Behaviour notes

- **Catalog:** `on_sale=true` means `sale_price_pkr < price_pkr`; `false` means everything else.
  `search` is a case-insensitive name match and treats `%` / `_` literally. Results are ordered
  newest first with stable tie-breakers, so pages never overlap.
- **Cart:** one cart per session, created on first add. Adding the same product/size/color again
  increases that line. `size` and `color` must be one of the product's options and may only be
  omitted when there is nothing to choose. Stock is checked across all lines of a product but not
  reserved. Concurrent adds to one cart are serialised with a row lock.
- **Prices:** `current_price_pkr` is the sale price when on sale, else the regular price. Cart totals
  use the current price.
- **CORS:** only the origins in `API_CORS_ORIGINS` (default: kiosk `:3000` and admin `:3001`); no credentials.
- **Logging:** one JSON object per line on stdout. Every response carries `X-Request-ID` (an inbound
  value is echoed if it is safe), and every log line emitted while handling a request includes it.
- **Async DB:** the catalog, products, sessions and cart routes use an async SQLAlchemy session
  (`app/core/db.py::get_async_db`). Alembic, the seed script and the try-on/upload/health routes,
  which call blocking clients, use the sync engine.

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
Route tests run against a migrated Postgres (each test in a rolled-back transaction) and skip if none is
reachable, so run them via `make test` with the stack up.

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

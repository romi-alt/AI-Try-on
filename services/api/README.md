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
| PATCH  | `/cart/{session_id}/items/{item_id}` | – | Set one cart line's quantity (`{"quantity": 1..99}`); returns the cart. 409 if there is not enough stock, 404 if the line is not in this session's cart |
| DELETE | `/cart/{session_id}/items/{item_id}` | – | Remove one cart line (all its quantity); returns the cart. 404 if the line is not in this session's cart or is already gone |
| POST   | `/checkout`                  | –      | Turn the session's cart into an order (pay at the counter); 201 with a pickup code, 409 if the cart is empty or stock is short. Resending the same `idempotency_key` returns the order already placed (200) |
| GET    | `/orders`                    | admin  | Recent orders, newest first; `code` finds one by its pickup code, `status` (`placed`, `collected`, `cancelled`) keeps one state |
| PATCH  | `/orders/{id}`               | admin  | `{"status": "collected" \| "cancelled"}`: close a waiting order. Cancelling returns its items to stock |
| POST   | `/capture`                   | –      | Upload a webcam photo (multipart `file` + `session_id`); returns its storage key |
| POST   | `/tryon`                     | –      | Queue a try-on for 1–5 `product_ids`; returns `job_id` immediately (202) |
| GET    | `/tryon/{id}`                | –      | Job row from Postgres: status, progress, result URL or error |
| GET    | `/jobs/{id}`                 | –      | Latest job state from Redis (falls back to Postgres): the polling fallback and reconnect read |
| WS     | `/ws?session={id}`           | –      | Live job events for one session (see Real-time updates) |
| POST   | `/uploads/presign`           | admin  | Presigned PUT URL for admin garment images   |
| POST   | `/uploads/verify`            | admin  | Check an uploaded garment image after the PUT; deletes it and answers 413/422 if it is too big, empty or the wrong type |
| GET    | `/tryon`                     | admin  | Recent jobs                                  |
| GET    | `/admin/stats`               | admin  | Dashboard counters                           |
| GET    | `/admin/analytics`           | admin  | Try-ons per product, try-on to cart rate, top recommended pairings (`days`, `limit`); definitions are in `app/api/analytics.py` |
| POST   | `/products/import`           | admin  | Bulk create/update from a CSV body (`text/csv`); upserts on `sku`; `dry_run=true` only checks; all or nothing with a per-row report |
| POST   | `/products/{id}/process`     | admin  | Queue background removal + garment mask (rembg + SAM 2) on the `assets` queue; progress shows in `processing_status` |
| POST   | `/products/embeddings`       | admin  | Queue FashionCLIP embeddings for some products or the whole catalog |
| GET    | `/recommend`                 | –      | `?product_ids=a,b`: `more_styles` (same-category nearest neighbours) and `complete_your_look` (one best match per missing top/bottom/shoes/bag) |
| POST   | `/share`                     | –      | Make (or find) the short code for a session's mobile page, optionally with one finished look |
| GET    | `/m/{code}`                  | code   | The mobile page's data: look image (fresh signed URL), cart, any order placed since. 404 unknown, 410 expired |
| POST   | `/m/{code}/checkout`         | code   | Place the order and charge it through the payment provider (stub); 402 if declined (order cancelled, stock and cart restored) |
| POST   | `/requests`                  | –      | "Request Outfit": ask staff to bring a product in a size; notifies staff (`NOTIFIER`) and publishes to the staff page |
| GET/PATCH | `/requests`, `/requests/{id}` | staff | List open requests; mark `bringing` or `done` |
| WS     | `/ws/staff`                  | staff  | Live request events. The first message must be `{"type":"auth","key":"<staff key>"}`; the server answers `{"type":"ready"}`, then read `GET /requests` |

## Behaviour notes

- **Catalog:** `on_sale=true` means `sale_price_pkr < price_pkr`; `false` means everything else.
  `search` is a case-insensitive name match and treats `%` / `_` literally. Results are ordered
  newest first with stable tie-breakers, so pages never overlap.
- **Cart:** one cart per session, created on first add. Adding the same product/size/color again
  increases that line. `size` and `color` must be one of the product's options and may only be
  omitted when there is nothing to choose. Stock is checked across all lines of a product but not
  reserved. Concurrent adds, quantity changes and removals on one cart are serialised with a row lock. A line's
  quantity can be set with `PATCH` and a line removed with `DELETE`. Raising a quantity is checked against stock
  across all of the product's lines (every size and colour), as when adding; lowering one is always allowed, even if
  stock has since dropped below what is in the cart. Removing a line frees its stock for later adds. Each cart
  product includes its current `stock`, so a client can stop offering "+" at the limit.
- **Prices:** `current_price_pkr` is the sale price when on sale, else the regular price. Cart totals
  use the current price.
- **CORS:** only the origins in `API_CORS_ORIGINS` (default: kiosk `:3000` and admin `:3001`); no credentials.
- **Logging:** one JSON object per line on stdout. Every response carries `X-Request-ID` (an inbound
  value is echoed if it is safe), and every log line emitted while handling a request includes it.
- **Async DB:** the catalog, products, sessions and cart routes use an async SQLAlchemy session
  (`app/core/db.py::get_async_db`). Alembic, the seed script and the try-on/upload/health routes,
  which call blocking clients, use the sync engine.

## Checkout

`POST /checkout` `{session_id, idempotency_key?}` turns the session's cart into an order. **There is no payment
step: the shopper pays at the counter and shows the six-character pickup code** (letters and digits chosen so they
cannot be misread, for example no 0/O or 1/I). Nothing about a card or a customer is collected or stored.

- **All or nothing.** The products are locked (in a fixed order, so concurrent checkouts cannot deadlock), stock is
  checked across every line of each product, and in one transaction the order is written, stock is reduced and the
  cart is emptied. If any item is short the answer is 409 naming it (`Not enough stock. Linen Shirt: only 1 left`)
  and nothing changes. An empty cart is also 409.
- **Prices are copied.** Names, options, image URL and the price at that moment are stored on the order, and
  `product_id` is not a foreign key, so later catalog edits or deleting a product cannot change an old order.
- **Retries.** A client that did not get an answer (timeout, dropped connection) cannot tell whether the order was
  placed. It sends the same `idempotency_key` again and gets the same order back (200) instead of a second one. The
  key is scoped to the session. The kiosk makes a new key for each attempt and keeps it only while the outcome is
  unknown.
- **Stock is taken at checkout, not at add-to-cart.** Several shoppers can still hold the last item in their carts;
  the first to check out gets it and the others are told it is sold out.
- **Order status.** An order starts `placed` (waiting for the shopper to pay and collect). Staff close it with
  `PATCH /orders/{id}` as `collected` (paid for and handed over; stock is untouched) or `cancelled` (not going
  ahead). **Cancelling puts every item back into stock** in the same transaction, locking the products in the same
  order as checkout; an item whose product has since been deleted is skipped, and the quantity is added to whatever
  the stock is now. Both are final: closing an order the other way is a 409 naming its current state. Asking for the
  state it is already in is a harmless repeat (200, nothing changes), so a double click or a retry cannot return the
  stock twice. The order row is locked, so two people acting on one order happen one at a time. `status_changed_at`
  records when. There is no un-cancel and no refund or payment record, because nothing is paid through this app.

## Garment image uploads

The admin app PUTs garment images straight to the bucket with a URL from `POST /uploads/presign` (admin key
required). A presigned PUT cannot limit the size of what is sent (a presigned POST policy could, but Cloudflare R2
does not support it), so the size is checked afterwards, in two places:

- **`POST /uploads/verify`** (`{key}`), called by the admin app right after the PUT. It reads the object's size and
  content type; an object over `GARMENT_MAX_BYTES` (default 10 MB, matching the admin app's own limit), empty, or
  stored under a type that does not match its key is **deleted** and refused (413 / 422). It only accepts keys of
  the form `/uploads/presign` produces, so it cannot be aimed at captures, results or anything else.
- **The sweeper** that already removes old captures also deletes any `garment/` object over the limit on every pass
  (every `CAPTURE_CLEANUP_INTERVAL_SECONDS`), so a file nobody verified does not stay.

Neither looks inside the file, so a small file with a valid type can still hold something that is not an image.

## Capture and try-on

**`POST /capture`** (multipart: `file`, `session_id`) accepts JPEG or WebP only. The format is detected from the
bytes, not the `Content-Type`. Limits and rules:

| Rule | Result |
|------|--------|
| larger than 5 MB | 413 (also enforced while the body streams, so oversized uploads are cut off early) |
| not JPEG/WebP, corrupt, animated | 415 / 422 |
| EXIF orientation | applied first, so a sideways phone photo is judged and stored as displayed |
| shorter than 768px, or not portrait | 422 with the measured size in the message |
| more than 40 megapixels | 422, checked from the header before decoding |
| unknown session | 404 |

The stored image is rebuilt from pixels as WebP, so EXIF, GPS, ICC and XMP cannot survive. It is saved as
`captures/{session_id}/{uuid}.webp` and the response is `{key, width, height, content_type, size_bytes,
expires_in_seconds}`.

**Retention.** Captures are personal photos and are deleted after `CAPTURE_TTL_SECONDS` (1 hour). Object-store
lifecycle rules only work in whole days, so the hour is enforced by a background sweeper in the API
(every `CAPTURE_CLEANUP_INTERVAL_SECONDS`, default 5 minutes). `make lifecycle` additionally installs a
1-day bucket rule as a coarse safety net in case the API is down. Generated results under `results/` have no
expiry rule yet.

**`POST /tryon`** takes `{session_id, capture_key, product_ids}`. The key must be one `/capture` issued to
that same session. It inserts a `queued` row, enqueues an RQ job (the RQ job id is the `tryon_jobs.id`) and
returns `{job_id, status: "queued", channel}` straight away. Follow it on the Redis channel
`session:{session_id}:job` (messages `{job, status, pct}`, then `{status: "done", url}` or
`{status: "failed", error}`), or poll `GET /tryon/{job_id}`. If Redis is down the job is marked failed and the
API answers 503.

## Real-time updates

Three pieces work together; the first is the source of truth for anything the others miss.

| | What | Use it for |
|--|------|------------|
| `GET /jobs/{id}` | The latest state, read from the Redis hash `job:{id}` (Postgres if the hash is missing or Redis is down). Sent with `Cache-Control: no-store`. | Polling fallback, and the first read after a (re)connect |
| `WS /ws?session={id}` | Every message published on `session:{id}:*`, forwarded as-is | Live progress |
| Redis hash `job:{id}` | `job`, `session`, `status`, `pct`, `updated_at`, plus `url` or `error`. Kept for `JOB_STATE_TTL_SECONDS` (a day) after the last update. | Written by the worker (and by the API for the first `queued` state) |

Updating the hash and publishing the message happen in **one Redis transaction**, so a client that subscribes
first and then reads `GET /jobs/{id}` can never miss an update: anything not in the read arrives on the socket.

**Messages** (JSON text frames). Job messages have no `type`; heartbeats do.

```json
{"job": "…", "status": "queued",     "pct": 0}
{"job": "…", "status": "processing", "pct": 40}
{"job": "…", "status": "done",       "pct": 100, "url": "https://…"}
{"job": "…", "status": "failed",     "pct": 40, "error": "readable message"}
{"type": "ping"}
```

**Connection behaviour**

- The Redis subscription is live **before** the handshake completes, so anything published once `onopen`
  fires is delivered. A client can connect first and then call `POST /tryon`.
- A `{"type": "ping"}` heartbeat is sent every `WS_HEARTBEAT_SECONDS` (25). Clients ignore it; it keeps idle
  connections open through proxies and lets a browser (which cannot see WebSocket ping frames) notice a dead
  server. Anything the client sends is ignored.
- `session` must be a UUID. Anything else, including a glob such as `*`, is refused before the handshake, so a
  client can only ever listen to the one session it names. Browser `Origin` headers must be in
  `API_CORS_ORIGINS`; clients that send no `Origin` are allowed.
- Redis unavailable at connect: the handshake is refused (HTTP 403), so the client should fall back to polling.
  Redis connection lost mid-stream: the socket closes with code 1011. Both mean "reconnect, then read
  `GET /jobs/{id}`".
- On disconnect (clean or abrupt) the server unsubscribes and closes its Redis connection.
- The session id is the only credential, as with the rest of the kiosk API. `GET /jobs/{id}` therefore never
  returns it, and job ids are random UUIDs.

**Client recipe**

```js
let socket, delay = 500;
function connect() {
  socket = new WebSocket(`${WS_URL}/ws?session=${sessionId}`);
  socket.onopen = async () => {
    delay = 500;
    if (jobId) apply(await (await fetch(`${API}/jobs/${jobId}`)).json()); // catch up, then rely on the socket
  };
  socket.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === "ping") return;
    if (!jobId || m.job === jobId) apply(m);   // apply() keeps the highest pct and stops at done/failed
  };
  socket.onclose = () => setTimeout(connect, (delay = Math.min(delay * 2, 10000)));
}
// If the socket cannot connect, poll GET /jobs/{id} every ~2s until status is done or failed.
```

## Data model

Migrations live in `alembic/versions/` (`make migrate`; `make migration m="..."` autogenerates).

| Table        | Notes                                                                                   |
|--------------|-----------------------------------------------------------------------------------------|
| `products`   | `category` enum (top, bottom, dress, shoes, bag, accessory); `price_pkr` / `sale_price_pkr` in whole rupees (sale never above price); `sizes`, `colors` jsonb; `stock >= 0`; `garment_image_url`, `garment_mask_url`; `embedding vector(512)` with an HNSW cosine index |
| `sessions`   | `started_at`, `consent_given`                                                           |
| `tryon_jobs` | `session_id`, `product_ids uuid[]` (at least one, not a FK so history survives catalog edits), `status` enum, `progress` 0-100, `person_image_key`, `result_url`, `error`, `created_at`, `updated_at` |
| `carts`      | one per session                                                                         |
| `cart_items` | `cart_id`, `product_id` (RESTRICT delete), optional `size` / `color`, `quantity > 0`    |
| `orders`     | `pickup_code` (unique), `status` enum (`placed`, `collected`, `cancelled`) and `status_changed_at`, `item_count`, `subtotal_pkr`, `session_id` (SET NULL), `idempotency_key` (unique per session) |
| `order_items`| copied `product_name`, `garment_image_url`, `size`, `color`, `quantity`, `unit_price_pkr`, `line_total_pkr`; `product_id` is not a foreign key |

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

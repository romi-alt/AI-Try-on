# services/api

FastAPI backend. Owns the catalog, kiosk sessions, presigned uploads and try-on job records.

## Endpoints

| Method | Path                         | Auth   | Purpose                                      |
|--------|------------------------------|--------|----------------------------------------------|
| GET    | `/health`, `/health/ready`   | –      | Liveness / readiness (checks Postgres+Redis) |
| GET    | `/garments`                  | –      | Active garments for the kiosk                |
| GET    | `/garments/{id}/similar`     | –      | pgvector nearest neighbours                  |
| POST/PATCH/DELETE | `/garments…`      | admin  | Catalog management                           |
| POST   | `/sessions`                  | –      | Start a kiosk session                        |
| POST   | `/sessions/{id}/end`         | –      | End a session                                |
| GET    | `/sessions`                  | admin  | Sessions with try-on counts                  |
| POST   | `/uploads/presign`           | –      | Presigned PUT URL for a capture/garment image|
| POST   | `/tryon`                     | –      | Enqueue a try-on job (returns 202)           |
| GET    | `/tryon/{id}`                | –      | Poll job status / result URL                 |
| GET    | `/tryon`                     | admin  | Recent jobs                                  |
| GET    | `/admin/stats`               | admin  | Dashboard counters                           |

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

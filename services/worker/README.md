# services/worker

Consumes try-on jobs from Redis (`tryon:jobs`), fetches the capture and garment
images from object storage, runs a provider, writes the result back to storage
and updates `tryon_jobs` in Postgres.

## Providers

| `TRYON_PROVIDER` | What it does                                                        |
|------------------|---------------------------------------------------------------------|
| `stub` (default) | Composites the garment PNG over the torso. No network, instant.     |
| `replicate`      | Calls a hosted VTON model on Replicate. Needs `REPLICATE_API_TOKEN`.|

Add a provider by subclassing `worker/providers/base.py::TryOnProvider` and
registering it in `worker/providers/__init__.py`.

## Run natively

```bash
cd services/worker
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m worker.main
```

The worker reads the `tryon_jobs` and `garments` tables created by the API's
Alembic migrations, so run `make migrate` first.

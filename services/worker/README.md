# services/worker

An [RQ](https://python-rq.org) worker. The API enqueues `worker.tasks.run_tryon_job(job_id)` on the `tryon`
queue; the worker loads the job from Postgres, renders it, uploads the result to object storage and reports
progress on Redis.

## What a job does

1. Claim the job (`queued` -> `processing`, atomic, so a redelivered job is not run twice).
2. Load the capture and the product images (own bucket through the S3 API, anything else over HTTP).
3. Run the provider. Progress is written to Postgres and published to `session:{session_id}:job`.
4. Convert the result to WebP, store it at `results/{session_id}/{job_id}.webp`, and make a signed GET URL
   (`RESULT_URL_EXPIRES_SECONDS`, default 1 hour).
5. Mark the job `done` and publish `{"job", "status": "done", "pct": 100, "url"}`.

Messages on the channel:

```json
{"job": "<id>", "status": "processing", "pct": 40}
{"job": "<id>", "status": "done",       "pct": 100, "url": "https://..."}
{"job": "<id>", "status": "failed",     "pct": 40,  "error": "Your photo is no longer available ..."}
```

Progress allocation: 0 started, 5 inputs loaded, 10-90 provider, 92 encoded, 97 uploaded, 100 done.

## Failures

Expected failures are recorded as `failed` with a message safe to show a shopper (expired photo, removed
product, a model that could not see the person, provider rate limits, timeouts, storage outages). Anything
unexpected shows a generic message and the full traceback goes to the logs only.

If a job process dies outright (for example an out-of-memory kill), RQ does not run the failure callback, so the
worker handles it explicitly: the parent fails the job immediately. If the whole worker dies, a reaper fails
any `processing` job with no update for `JOB_TIMEOUT_SECONDS` plus 60s, at startup and periodically.

## Providers (`TRYON_PROVIDER`)

| Value | Behaviour |
|-------|-----------|
| `mock` (default) | Waits `MOCK_DURATION_SECONDS` (8) in `MOCK_STEPS` steps, reports progress, returns the photo with each garment pasted on and a banner. `MOCK_FAIL=true` forces a failure. |
| `fashn` | [FASHN](https://docs.fashn.ai) `tryon-v1.6` over HTTP: `POST /v1/run`, poll `GET /v1/status/{id}`, download `output[0]`. Needs `FASHN_API_KEY` (read from the environment, never committed). Tops, bottoms and dresses only; an outfit is applied one garment at a time, each result becoming the next input. Rate limits and server errors are retried; every error is mapped to a shopper-readable message. |

The worker refuses to start with an unknown provider or with `fashn` and no key.

Add a provider by subclassing `worker/providers/base.py::TryOnProvider` (`run(request, on_progress)`; raise
`ProviderError("message safe to show")` for expected failures) and registering it in
`worker/providers/__init__.py` and the `TRYON_PROVIDER` setting.

## Run natively

```bash
cd services/worker
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m worker.main
```

Run `make migrate` first: the worker reads the `tryon_jobs` and `products` tables the API's Alembic
migrations create (`tests/test_schema_contract.py` checks they still match).

## Tests

```bash
pytest -q
```

Provider tests need nothing. The job tests use a throwaway Postgres schema, real Redis pub/sub and an in-process
S3 server (moto), and skip when Postgres or Redis is not reachable.

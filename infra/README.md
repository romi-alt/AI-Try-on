# infra

Local development infrastructure, driven from the repo root `Makefile`.

| Service      | Image                      | Host port | Notes                                   |
|--------------|----------------------------|-----------|-----------------------------------------|
| postgres     | `pgvector/pgvector:pg16`   | 5432      | `vector` extension created by `init.sql`|
| redis        | `redis:7-alpine`           | 6379      | job queue + pub/sub for progress        |
| minio        | `minio/minio`              | 9000/9001 | S3-compatible stand-in for Cloudflare R2|
| minio-init   | `minio/mc`                 | –         | creates the bucket, sets public read    |
| api          | `../services/api`          | 8000      | FastAPI, hot reload                     |
| worker       | `../services/worker`       | –         | consumes `tryon:jobs`                   |
| kiosk        | `../apps/kiosk`            | 3000      | Next.js dev server                      |
| admin        | `../apps/admin`            | 3001      | Next.js dev server                      |

## Cloudflare R2 in production

R2 is S3-compatible. Point the same env vars at R2 instead of MinIO:

```
S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
S3_REGION=auto
S3_BUCKET=<bucket>
S3_ACCESS_KEY_ID=<r2 access key>
S3_SECRET_ACCESS_KEY=<r2 secret>
S3_PUBLIC_BASE_URL=https://<your-public-r2-domain>
S3_PRESIGN_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
```

Nothing else in the code changes.

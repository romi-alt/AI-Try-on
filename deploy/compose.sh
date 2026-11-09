#!/usr/bin/env bash
# `docker compose` for the production stack, from anywhere: ./compose.sh ps | logs -f api | up -d | ...
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .env.production ]; then
  echo "deploy/.env.production is missing. Copy .env.production.example and fill it in." >&2
  exit 1
fi
exec docker compose --env-file .env.production -f docker-compose.prod.yml "$@"

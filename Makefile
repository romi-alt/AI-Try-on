# AI Try-On Mirror — developer entrypoints
# Usage: make <target>   (run `make help` to list targets)

SHELL := /bin/bash
COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml
API_EXEC := $(COMPOSE) exec api

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: env
env: ## Create .env files from the examples (does not overwrite existing files)
	@test -f .env || cp .env.example .env
	@test -f apps/kiosk/.env.local || cp apps/kiosk/.env.example apps/kiosk/.env.local
	@test -f apps/admin/.env.local || cp apps/admin/.env.example apps/admin/.env.local
	@test -f services/api/.env || cp services/api/.env.example services/api/.env
	@test -f services/worker/.env || cp services/worker/.env.example services/worker/.env
	@echo "env files ready"

.PHONY: install
install: ## Install JS workspace deps (Python deps are installed inside containers)
	npm install

.PHONY: dev
dev: env ## Start the full local stack (postgres+pgvector, redis, minio, api, worker, kiosk, admin)
	$(COMPOSE) up --build

.PHONY: dev-infra
dev-infra: env ## Start only infra (postgres, redis, minio) — run apps natively on the host
	$(COMPOSE) up -d postgres redis minio minio-init

.PHONY: down
down: ## Stop the stack and keep volumes
	$(COMPOSE) down

.PHONY: clean
clean: ## Stop the stack and delete volumes (destroys local DB + bucket data)
	$(COMPOSE) down -v --remove-orphans

.PHONY: logs
logs: ## Tail logs for all services
	$(COMPOSE) logs -f --tail=100

.PHONY: ps
ps: ## Show running services
	$(COMPOSE) ps

.PHONY: migrate
migrate: ## Run Alembic migrations against the dev database
	$(API_EXEC) alembic upgrade head

.PHONY: migration
migration: ## Autogenerate a new Alembic migration: make migration m="add foo"
	$(API_EXEC) alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## Seed the database and bucket with 20 demo products
	$(API_EXEC) python -m scripts.seed

.PHONY: api-shell
api-shell: ## Open a shell in the api container
	$(API_EXEC) bash

.PHONY: psql
psql: ## Open psql against the dev database
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-tryon} -d $${POSTGRES_DB:-tryon}

.PHONY: test
test: ## Run API and worker tests (needs the stack up and `make migrate` done)
	$(API_EXEC) pytest -q
	$(COMPOSE) exec worker pytest -q

.PHONY: test-kiosk
test-kiosk: ## Run the kiosk's unit tests (host Node; no services needed)
	npm test --workspace apps/kiosk

.PHONY: lifecycle
lifecycle: ## Add the bucket lifecycle rule that expires captures/ after a day (backstop to the 1h sweeper)
	$(API_EXEC) python -m scripts.apply_lifecycle

.PHONY: lint
lint: ## Lint all packages
	npm run lint --workspaces --if-present
	$(API_EXEC) ruff check .
	$(COMPOSE) exec worker ruff check .

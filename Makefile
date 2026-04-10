# AscenAI — Developer + Ops Makefile
#
# Common workflows:
#   make dev          — start full stack locally
#   make prod         — start with production overrides
#   make test         — run all tests
#   make migrate      — run DB migrations
#   make lint         — lint all services
#   make build        — build all Docker images

.PHONY: help dev prod down logs test lint migrate migrate-new build clean

# Default: show help
help:
	@echo ""
	@echo "  AscenAI — Available commands"
	@echo "  ─────────────────────────────────────────────────────"
	@echo "  make dev              Start full stack (dev mode)"
	@echo "  make prod             Start with production overrides"
	@echo "  make down             Stop all containers"
	@echo "  make logs             Tail all service logs"
	@echo "  make logs s=api-gateway   Tail a specific service"
	@echo ""
	@echo "  make migrate          Apply pending DB migrations"
	@echo "  make migrate-new m='msg'  Generate new migration"
	@echo "  make migrate-downgrade    Roll back latest migration"
	@echo ""
	@echo "  make test             Run all tests"
	@echo "  make test-api         Run api-gateway tests only"
	@echo "  make lint             Lint all Python services"
	@echo "  make build            Build all Docker images"
	@echo "  make clean            Remove containers and volumes"
	@echo ""

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------
dev:
	docker compose up --build -d
	@echo "Services started → http://localhost:3000"

prod:
	@test -f .env || (echo "ERROR: .env file missing. Copy .env.example and fill in values." && exit 1)
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
	@echo "Production stack started."

down:
	docker compose down

logs:
ifdef s
	docker compose logs -f $(s)
else
	docker compose logs -f
endif

# ---------------------------------------------------------------------------
# Database Migrations (Alembic)
# ---------------------------------------------------------------------------
migrate:
	@echo "→ api-gateway migrations"
	docker compose run --rm api-gateway sh -c "cd /app && alembic upgrade head"
	@echo "→ mcp-server migrations"
	docker compose run --rm mcp-server sh -c "cd /app && alembic upgrade head"

migrate-new:
ifndef m
	$(error Usage: make migrate-new m="describe your change")
endif
	@echo "→ generating api-gateway migration: $(m)"
	docker compose run --rm api-gateway sh -c "cd /app && alembic revision --autogenerate -m '$(m)'"

migrate-downgrade:
	docker compose run --rm api-gateway sh -c "cd /app && alembic downgrade -1"

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test: test-api

test-api:
	@echo "→ running api-gateway tests"
	cd services/api-gateway && \
	  DATABASE_URL=sqlite+aiosqlite:///./test.db \
	  REDIS_URL=redis://localhost:6379/0 \
	  SECRET_KEY=test-secret-key-for-unit-tests-32chars!! \
	  ENVIRONMENT=test \
	  python -m pytest tests/ -v --tb=short

# ---------------------------------------------------------------------------
# Linting
# ---------------------------------------------------------------------------
lint:
	@for svc in api-gateway mcp-server ai-orchestrator voice-pipeline; do \
	  echo "→ linting $$svc"; \
	  ruff check services/$$svc/app --select E,W,F,I --ignore E501,E402,F401 || true; \
	done

lint-fix:
	@for svc in api-gateway mcp-server ai-orchestrator voice-pipeline; do \
	  ruff check services/$$svc/app --fix --select E,W,F,I --ignore E501,E402,F401 || true; \
	  ruff format services/$$svc/app || true; \
	done

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
build:
	docker compose build

# Rebuild a single service: make build-one s=api-gateway
build-one:
ifdef s
	docker compose build $(s)
else
	$(error Usage: make build-one s=<service-name>)
endif

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
clean:
	docker compose down -v --remove-orphans
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find services/api-gateway -name "test.db" -delete 2>/dev/null || true

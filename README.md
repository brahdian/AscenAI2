# AscenAI

AI agent platform for small businesses — build, deploy, and manage conversational AI agents with voice support, guardrails, and conversational learning.

## Architecture

| Service | Port | Description |
|---|---|---|
| **api-gateway** | 8000 | Auth, rate limiting, reverse proxy |
| **mcp-server** | 8001 | Tool registry and execution (MCP protocol) |
| **ai-orchestrator** | 8002 | Agent logic, LLM routing, sessions |
| **voice-pipeline** | 8003 | STT → AI → TTS real-time voice |
| **frontend** | 3000 | Next.js dashboard |
| **postgres** | 5432 | Primary database + Vector store (pgvector) |
| **redis** | 6379 | Cache, rate limiting, sessions |

---

## Quickstart — OrbStack (recommended for macOS)

[OrbStack](https://orbstack.dev) is a fast, lightweight Docker engine for macOS. It starts in under 2 seconds, uses less RAM than Docker Desktop, and is free for personal use.

A single script handles everything — installing OrbStack, generating secrets, and starting all services:

```bash
bash setup-orbstack.sh
```

The script will:
1. Install Homebrew (if missing)
2. Install OrbStack via Homebrew (if missing)
3. Start the Docker engine
4. Copy `.env.example` → `.env` and auto-generate a strong `SECRET_KEY`
5. Prompt for your LLM API key (Gemini/OpenAI) if not already set
6. Run `docker compose up --build -d`
7. Wait for all services to pass health checks
8. Print URLs for the dashboard and all API docs

Once complete, open **http://localhost:3000** and register your account.

---

## Running on macOS

### Prerequisites

Install the following if you don't have them already:

```bash
# Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Docker Desktop — download from https://www.docker.com/products/docker-desktop/
# After installing, open Docker Desktop and wait for it to show "Engine running"

# Verify Docker is running
docker --version
docker compose version
```

> Docker Desktop for Mac includes both `docker` and `docker compose`. You need at least Docker Desktop 4.x.

---

### 1. Clone the repository

```bash
git clone https://github.com/brahdian/ascenai2.git
cd ascenai2
```

---

### 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` in your editor and fill in the required values:

```bash
# Generate a strong secret key (run this in your terminal):
python3 -c "import secrets; print(secrets.token_hex(32))"
# Paste the output as the value for SECRET_KEY in .env
```

**Required fields:**

| Variable | Description |
|---|---|
| `SECRET_KEY` | Random 32+ char string (generate above) |
| `LLM_PROVIDER` | `gemini`, `openai`, or `vertex` |
| `GEMINI_API_KEY` | Required if using `LLM_PROVIDER=gemini` |
| `OPENAI_API_KEY` | Required if using `LLM_PROVIDER=openai` |

**Optional fields** (leave blank to skip):

| Variable | Description |
|---|---|
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` | Password reset emails |
| `ELEVENLABS_API_KEY` | Higher-quality TTS voices |
| `DEEPGRAM_API_KEY` | Alternative STT provider |
| `SENTRY_DSN` | Error tracking |
| `STRIPE_SECRET_KEY` | Billing |

---

### 3. Start all services

```bash
docker compose up --build
```

This will:
- Pull Postgres 16 (pgvector) and Redis 7 images
- Build all four Python backend services
- Build the Next.js frontend
- Run database initialization from `shared/db/init.sql`

First build takes ~3–5 minutes. Subsequent starts are fast.

To run in the background:

```bash
docker compose up --build -d
```

---

### 4. Open the dashboard

Once all services are healthy, open your browser:

```
http://localhost:3000
```

Register a new account to get started. The first registered user becomes the tenant owner.

---

### 5. Verify services are running

```bash
# Check all containers
docker compose ps

# Health check each service
curl http://localhost:8000/health   # api-gateway
curl http://localhost:8001/health   # mcp-server
curl http://localhost:8002/health   # ai-orchestrator
curl http://localhost:8003/health   # voice-pipeline
```

All should return `{"status": "ok", ...}`.

---

### Useful commands

```bash
# View logs for all services
docker compose logs -f

# View logs for a specific service
docker compose logs -f api-gateway
docker compose logs -f ai-orchestrator

# Stop all services (keeps data)
docker compose down

# Stop and wipe all data (postgres, redis volumes)
docker compose down -v

# Rebuild a single service after code changes
docker compose up --build api-gateway

# Open a Postgres shell
docker compose exec postgres psql -U postgres -d ascenai

# Open a Redis shell
docker compose exec redis redis-cli
```

---

### API documentation

Each backend service exposes interactive Swagger docs:

| Service | Docs URL |
|---|---|
| api-gateway | http://localhost:8000/docs |
| mcp-server | http://localhost:8001/docs |
| ai-orchestrator | http://localhost:8002/docs |
| voice-pipeline | http://localhost:8003/docs |

---

### Troubleshooting

**Docker Desktop not running**
> Error: `Cannot connect to the Docker daemon`

Open Docker Desktop from Applications and wait for the whale icon in your menu bar to stop animating.

**Port already in use**
> Error: `Bind for 0.0.0.0:5432 failed: port is already allocated`

Stop any local Postgres/Redis instances:
```bash
brew services stop postgresql
brew services stop redis
```

Or change the host port in `docker-compose.yml` (e.g. `"5433:5432"`).

**Services unhealthy / keep restarting**

Check logs for the failing service:
```bash
docker compose logs api-gateway
```

The most common cause is a missing or weak `SECRET_KEY` in `.env`. Make sure it is at least 32 characters and not one of the example placeholder values.

**Apple Silicon (M1/M2/M3)**

All images support `linux/arm64`. If you see a platform warning, add this to your shell profile:
```bash
export DOCKER_DEFAULT_PLATFORM=linux/arm64
```

---

### Development (running services locally without Docker)

If you prefer to run services natively for faster iteration:

**Requirements:**
- Python 3.11+: `brew install python@3.11`
- Node.js 20+: `brew install node`
- Postgres and Redis still running via Docker:

```bash
# Start only infrastructure
docker compose up -d postgres redis
```

**Backend services:**

```bash
# In separate terminals, one per service:

cd services/api-gateway
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

cd services/mcp-server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001

cd services/ai-orchestrator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8002

cd services/voice-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8003
```

Each service reads `.env` from the repo root. Set `DATABASE_URL`, `REDIS_URL`, and `QDRANT_HOST` to point at `localhost` instead of the Docker service names:

```bash
# Override for local dev (add to your shell or a local .env.local)
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ascenai
export REDIS_URL=redis://localhost:6379/0
```

**Frontend:**

```bash
cd frontend/web
npm install
npm run dev
# Opens at http://localhost:3000
```

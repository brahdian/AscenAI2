# Getting Started with AscenAI2

**Last updated:** 2026-04-02
**Version:** 2.0.0

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Quick Start](#2-quick-start)
3. [First-Time Setup](#3-first-time-setup)
4. [Accessing the Dashboard](#4-accessing-the-dashboard)
5. [Creating Your First Agent](#5-creating-your-first-agent)
6. [Next Steps](#6-next-steps)

---

## 1. Prerequisites

Before running AscenAI2, ensure the following are installed on your system:

| Software | Minimum Version | Purpose |
|----------|----------------|---------|
| [Docker](https://docs.docker.com/get-docker/) | 24.0+ | Container runtime |
| [Docker Compose](https://docs.docker.com/compose/install/) | 2.20+ | Multi-container orchestration |
| [Node.js](https://nodejs.org/) | 18+ | Frontend development (optional) |
| [Python](https://www.python.org/) | 3.11+ | Backend development (optional) |
| [Git](https://git-scm.com/) | 2.40+ | Source control |

### System Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8+ GB |
| Disk | 10 GB | 20+ GB |

---

## 2. Quick Start

### 2.1 Clone the Repository

```bash
git clone <repository-url>
cd AscenAI
```

### 2.2 Configure Environment Variables

Copy the example environment file and edit it with your settings:

```bash
cp .env.example .env
```

At minimum, set the following variables in `.env`:

```bash
# Security -- generate with: openssl rand -hex 32
SECRET_KEY=<generate-a-strong-random-key>

# LLM Provider (pick one)
LLM_PROVIDER=gemini
GEMINI_API_KEY=<your-gemini-api-key>

# Database (defaults are fine for local dev)
POSTGRES_PASSWORD=change-this-postgres-password
```

### 2.3 Start All Services

```bash
docker compose up -d
```

This starts the following services:

| Service | Port | Description |
|---------|------|-------------|
| PostgreSQL | 5432 | Database with pgvector extension |
| Redis | 6379 | Session store, cache, rate limiting |
| MailHog | 8025 (UI), 1025 (SMTP) | Email testing (development only) |
| API Gateway | 8000 | Main API entry point |
| MCP Server | 8001 | Tool execution and context retrieval |
| AI Orchestrator | 8002 | LLM reasoning, memory, guardrails |
| Voice Pipeline | 8003 | STT to LLM to TTS voice pipeline |
| Frontend | 3000 | Next.js dashboard |

### 2.4 Verify Services Are Running

```bash
docker compose ps
```

All services should show `running` status. Check individual service health:

```bash
# API Gateway
curl http://localhost:8000/health

# MCP Server
curl http://localhost:8001/health

# AI Orchestrator
curl http://localhost:8002/health

# Voice Pipeline
curl http://localhost:8003/health
```

### 2.5 View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api-gateway
docker compose logs -f ai-orchestrator
```

---

## 3. First-Time Setup

### 3.1 Register an Account

1. Open your browser and navigate to `http://localhost:3000`.
2. Click **Sign Up** on the login page.
3. Fill in the registration form:
   - **Business name**: Your company or project name
   - **Email**: Your email address (used for login and verification)
   - **Password**: A strong password (min. 8 characters)
   - **Business type**: Select your industry (pizza_shop, clinic, salon, other)
4. Click **Register**.

### 3.2 Verify Your Email

After registration, an OTP (One-Time Password) is sent to your email:

- **Development**: Open MailHog at `http://localhost:8025` to view the email.
- **Production**: Check your inbox (configured via SendGrid or SMTP in `.env`).

Enter the 6-digit OTP on the verification page to activate your account.

### 3.3 Subscribe to a Plan

AscenAI2 requires an active subscription to create agents. Available plans:

| Plan | Price/Agent | Chat Equivalents | Voice Minutes | Voice Enabled |
|------|-------------|-----------------|---------------|---------------|
| **Starter** | $49/mo | 20,000 | 0 | No |
| **Growth** | $99/mo | 80,000 | 1,500 | Yes |
| **Business** | $199/mo | 170,000 | 3,500 | Yes |
| **Enterprise** | Custom | Custom | Custom | Yes |

To subscribe:

1. After email verification, you will be prompted to choose a plan.
2. Select your plan and click **Subscribe**.
3. You will be redirected to a Stripe Checkout page to complete payment.
4. Upon successful payment, your account is activated immediately.

> **Note**: The system uses a "chat equivalent" billing model where 1 voice minute = 100 chat equivalents. Overage is charged at $0.002 per chat equivalent beyond your plan limit.

### 3.4 Log In

After activation, log in with your email and password. JWT tokens are stored as HttpOnly cookies for security.

---

## 4. Accessing the Dashboard

The Next.js frontend dashboard is available at `http://localhost:3000` (or your configured `FRONTEND_URL`).

### 4.1 Dashboard Sections

| Section | Description |
|---------|-------------|
| **Overview** | Summary of active agents, sessions, and usage metrics |
| **Agents** | Create, configure, and manage AI agents |
| **Sessions** | View active and historical conversation sessions |
| **Playbooks** | Design structured conversation flows |
| **Documents** | Upload knowledge base files for RAG |
| **Billing** | View usage, estimated costs, and manage subscription |
| **Settings** | Team management, API keys, webhooks, compliance |

### 4.2 API Documentation

Interactive API docs are available at:

- **API Gateway**: `http://localhost:8000/docs` (Swagger UI)
- **MCP Server**: `http://localhost:8001/docs`
- **AI Orchestrator**: `http://localhost:8002/docs` (limited -- use gateway proxy)

---

## 5. Creating Your First Agent

### 5.1 Via the Dashboard

1. Navigate to **Agents** in the sidebar.
2. Click **Create Agent**.
3. Fill in the agent details:
   - **Name**: A descriptive name (e.g., "Customer Support Bot")
   - **Description**: What the agent does
   - **Business type**: pizza_shop, clinic, salon, or generic
   - **Personality**: Tone and style (professional, friendly, casual, empathetic)
   - **System prompt**: Custom instructions for the agent (optional)
   - **Language**: Default language (default: English)
   - **Voice enabled**: Toggle voice capability (requires Growth plan or higher)
4. Click **Create**.

### 5.2 Via the API

```bash
curl -X POST http://localhost:8000/api/v1/proxy/agents \
  -H "Content-Type: application/json" \
  -H "Cookie: access_token=<your-token>" \
  -d '{
    "name": "Customer Support Bot",
    "description": "Handles customer inquiries and bookings",
    "business_type": "generic",
    "personality": "friendly",
    "language": "en",
    "voice_enabled": true
  }'
```

### 5.3 Testing Your Agent

Once created, you can test your agent:

1. Go to the agent's detail page.
2. Use the built-in chat widget to send a test message.
3. The agent will respond using the configured LLM (Gemini by default).

### 5.4 Configuring Tools

Agents can be equipped with tools for external integrations:

1. Navigate to your agent's **Tools** tab.
2. Enable built-in tools (Stripe payments, Google Calendar, Twilio SMS, etc.) or add custom tools.
3. Configure credentials for each tool in the MCP Server.

### 5.5 Setting Up Playbooks

Playbooks define structured conversation flows:

1. Navigate to **Playbooks** in the sidebar.
2. Create a new playbook with intent triggers, instructions, and scenarios.
3. Associate the playbook with your agent.

---

## 6. Next Steps

- Read the [Architecture Overview](./ARCHITECTURE.md) to understand how the system works.
- Follow the [Development Guide](./DEVELOPMENT.md) to set up a local development environment.
- Configure [Voice Integration](./VOICE_SETUP.md) for phone-based interactions.
- Set up [Payment Integration](./PAYMENTS.md) for production billing.
- Review the [API Reference](./API_REFERENCE.md) for programmatic access.
- See [Deployment Guide](./DEPLOYMENT.md) for production deployment.
- Check [Troubleshooting](./TROUBLESHOOTING.md) for common issues.

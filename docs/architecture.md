# Architecture Overview

**Version:** 2.0.0 | **Last Updated:** 2026-04-02

This document provides a comprehensive overview of the AscenAI2 system architecture, including service topology, data flows, database schema, and infrastructure components.

---

## Table of Contents

1. [System Architecture Diagram](#1-system-architecture-diagram)
2. [Service Overview](#2-service-overview)
3. [Data Flow: Text Chat](#3-data-flow-text-chat)
4. [Data Flow: Voice](#4-data-flow-voice)
5. [Database Schema](#5-database-schema)
6. [Redis Usage](#6-redis-usage)
7. [Stripe Integration](#7-stripe-integration)
8. [Security Architecture](#8-security-architecture)

---

## 1. System Architecture Diagram

```
                        ┌─────────────────────────────────────────────────┐
                        │                  CLIENTS                        │
                        │  Browser (Next.js)  │  Twilio (Voice)  │  SDK  │
                        └────────┬────────────┴────────┬───────────┴─────┘
                                 │                     │
                          HTTP/WS│                     │SIP/RTP
                                 │                     │
                    ┌────────────▼─────────────────────▼────────────┐
                    │              NGINX (Production)               │
                    │         TLS Termination + Reverse Proxy       │
                    └────────────┬─────────────────────┬────────────┘
                                 │                     │
                    ┌────────────▼─────────────────────▼────────────┐
                    │              API GATEWAY (:8000)              │
                    │  ┌─────────┐ ┌──────────┐ ┌───────────────┐  │
                    │  │  Auth   │ │   Rate   │ │  Plan/Limit   │  │
                    │  │  (JWT)  │ │  Limit   │ │  Enforcement  │  │
                    │  └─────────┘ └──────────┘ └───────────────┘  │
                    │  ┌─────────────────────────────────────────┐  │
                    │  │         Reverse Proxy Router            │  │
                    │  │  /agents/*   → AI Orchestrator (:8002)  │  │
                    │  │  /tools/*    → MCP Server (:8001)       │  │
                    │  │  /voice/*    → Voice Pipeline (:8003)   │  │
                    │  └─────────────────────────────────────────┘  │
                    └──────┬──────────────┬──────────────┬──────────┘
                           │              │              │
              ┌────────────▼────┐  ┌──────▼──────┐  ┌───▼──────────────┐
              │  AI ORCHESTRATOR│  │  MCP SERVER │  │  VOICE PIPELINE  │
              │     (:8002)     │  │  (:8001)    │  │     (:8003)      │
              │                 │  │             │  │                  │
              │ ┌─────────────┐ │  │ ┌─────────┐ │  │ ┌──────────────┐ │
              │ │ Orchestrator│ │  │ │  Tool   │ │  │ │ STT Service  │ │
              │ │ PII Service │ │  │ │ Registry│ │  │ │ TTS Service  │ │
              │ │ Memory Mgr  │ │  │ │ Executor│ │  │ │ Voice Guard  │ │
              │ │ Playbook    │ │  │ │ Context │ │  │ │ Barge-in     │ │
              │ │ LLM Client  │ │  │ │ Provider│ │  │ │ VAD Engine   │ │
              │ │ Sem. Cache  │ │  │ │ Auth Mgr│ │  │ └──────┬───────┘ │
              │ │ Moderation  │ │  │ └─────────┘ │  │        │         │
              │ │ Model Router│ │  └──────┬──────┘  │        │         │
              │ └──────┬──────┘ │         │         │        │         │
              │        │        │         │         │        │         │
              │   ┌────▼────┐   │    ┌────▼────┐    │   ┌────▼────┐    │
              │   │ LLM API  │   │    │External │    │   │ AI Orch │    │
              │   │(Gemini/  │   │    │ APIs    │    │   │ (:8002) │    │
              │   │ OpenAI)  │   │    │(Stripe, │    │   └─────────┘    │
              │   └─────────┘   │    │ GCal,   │    └──────────────────┘
              └─────────────────┘    │ Twilio) │
                                     └─────────┘

                    ┌─────────────────────────────────────┐
                    │            DATA LAYER               │
                    │                                     │
                    │  ┌──────────────┐  ┌──────────────┐ │
                    │  │  PostgreSQL  │  │    Redis 7    │ │
                    │  │  16+pgvector │  │              │ │
                    │  │              │  │  Sessions    │ │
                    │  │  23+ Tables  │  │  Sem. Cache  │ │
                    │  │  RLS Policies│  │  Rate Limits │ │
                    │  │  Vector Search│ │  PII Context │ │
                    │  └──────────────┘  │  OTP Storage │ │
                    │                    │  LTM Cache   │ │
                    │                    └──────────────┘ │
                    └─────────────────────────────────────┘
```

---

## 2. Service Overview

### 2.1 API Gateway (:8000)

**Technology:** FastAPI (Python), Uvicorn (4 workers in production)

**Role:** Single entry point for all external HTTP traffic. Handles authentication, rate limiting, plan enforcement, and request routing.

**Key Responsibilities:**
- JWT authentication and cookie management
- Per-tenant rate limiting (300 req/min authenticated, 30 req/min unauthenticated)
- Plan limit enforcement (agent slots, message quotas)
- Reverse proxy to internal services
- Stripe webhook handling for billing
- Admin portal and compliance endpoints

**Routers (10 total):**
| Router | Prefix | Purpose |
|--------|--------|---------|
| Auth | `/api/v1/auth` | Registration, login, OTP, password reset |
| Tenants | `/api/v1/tenants` | Tenant CRUD operations |
| Users | `/api/v1/users` | User management within tenants |
| API Keys | `/api/v1/api-keys` | API key lifecycle management |
| Webhooks | `/api/v1/webhooks` | Outbound webhook configuration |
| Billing | `/api/v1/billing` | Subscription, usage, Stripe integration |
| Compliance | `/api/v1/compliance` | Audit logs, data export |
| Proxy | `/api/v1/proxy` | Reverse proxy to internal services |
| Team | `/api/v1/team` | Team member management |
| Admin | `/api/v1/admin` | Platform administration |

**Middleware Stack (outermost to innermost):**
1. CORS (handles preflight for all responses)
2. W3C Traceparent propagation
3. Request logging (trace ID, timing)
4. Auth middleware (JWT validation, tenant resolution)
5. Rate limiting (Redis-backed sliding window)

### 2.2 MCP Server (:8001)

**Technology:** FastAPI (Python), Uvicorn (2 workers in production)

**Role:** Model Context Protocol server providing standardized tool execution and context retrieval. Decouples the AI Orchestrator from external service integrations.

**Key Responsibilities:**
- Tool registry (CRUD for tool definitions per tenant)
- Tool execution (built-in handlers + HTTP endpoints)
- RAG context retrieval (pgvector semantic search)
- Authentication header resolution for external APIs
- Per-tool rate limiting

**Built-in Tool Categories (25+ tools):**
| Category | Tools |
|----------|-------|
| Demo | `pizza_order`, `order_status`, `appointment_book/list/cancel`, `crm_lookup/update`, `send_sms` |
| Calendar | `calendar_check_availability`, `calendar_book_appointment`, `calendly_availability`, `calendly_book` |
| Payment | `stripe_payment_link`, `stripe_check_payment`, `helcim_process_payment`, `paypal_create_order`, `moneris_process_payment`, `square_create_payment` |
| Communication | `twilio_send_sms`, `gmail_send_email`, `mailchimp_add_subscriber`, `telnyx_send_bulk_sms` |
| Productivity | `google_sheets_read`, `google_sheets_append` |
| Custom | `custom_webhook` (arbitrary HTTP endpoints) |

**Routers (4 total):**
| Router | Prefix | Purpose |
|--------|--------|---------|
| Tools | `/api/v1/tools` | Tool CRUD and listing |
| Execution | `/api/v1/execute` | Tool execution endpoint |
| Context | `/api/v1/context` | RAG retrieval (knowledge, history, customer) |
| Streaming | `/ws` | WebSocket streaming for tool execution |

### 2.3 AI Orchestrator (:8002)

**Technology:** FastAPI (Python), Uvicorn (2 workers in production)

**Role:** The cognitive core of the platform. Manages the complete request lifecycle from message intake to response delivery.

**Key Components:**
| Component | Purpose |
|-----------|---------|
| Orchestrator | Main processing loop (38 steps per turn) |
| PII Service | Reversible pseudonymization (Presidio-backed) |
| Memory Manager | 3-tier memory (short-term, summary, long-term) |
| Playbook Engine | Declarative state machine for structured flows |
| LLM Client | Multi-provider abstraction (Gemini, OpenAI, Vertex) |
| Semantic Cache | Embedding-based response caching (threshold >= 0.92) |
| Moderation Service | Content moderation (OpenAI API + detoxify fallback) |
| Model Router | Automatic model tier selection based on complexity |
| Trace Logger | Full conversation trace persistence |
| Document Indexer | Background worker for RAG document processing |
| Session Cleanup | Background worker for expired session cleanup |

**Routers (15 total):**
| Router | Prefix | Purpose |
|--------|--------|---------|
| Chat | `/api/v1/chat` | Chat endpoint (text + streaming) |
| Agents | `/api/v1/agents` | Agent CRUD |
| Sessions | `/api/v1/sessions` | Session management |
| Feedback | `/api/v1/feedback` | Thumbs up/down + corrections |
| Analytics | `/api/v1/analytics` | Usage analytics |
| Playbooks | `/api/v1/agents/{id}/playbooks` | Playbook CRUD |
| Guardrails | `/api/v1/agents/{id}/guardrails` | Guardrails configuration |
| Learning | `/api/v1/agents/{id}/learning` | Learning insights |
| Documents | `/api/v1/agents/{id}/documents` | Knowledge base management |
| Internal | `/api/v1/internal` | Service-to-service endpoints |
| Replay | `/api/v1/replay` | Conversation replay for debugging |
| Evals | `/api/v1/agents/{id}/evals` | Evaluation cases and runs |
| Prompts | `/api/v1/agents/{id}/prompts` | Prompt versioning and A/B tests |
| Templates | `/api/v1/templates` | Agent template management |
| Variables | `/api/v1/agents/{id}/variables` | Agent variable CRUD |

**WebSocket Endpoint:**
- `/ws/{tenant_id}/{session_id}` - Real-time streaming chat with JWT authentication

### 2.4 Voice Pipeline (:8003)

**Technology:** FastAPI (Python), Uvicorn (2 workers in production)

**Role:** Real-time voice interaction pipeline: Speech-to-Text (STT) -> AI Orchestrator -> Text-to-Speech (TTS).

**Key Components:**
| Component | Purpose |
|-----------|---------|
| STT Service | Speech-to-Text (Gemini, OpenAI, Deepgram) |
| TTS Service | Text-to-Speech (Cartesia, Google, ElevenLabs, OpenAI) |
| Voice Pipeline | Full duplex conversation manager |
| VAD Engine | Energy-based Voice Activity Detection |
| Barge-in Handler | Interrupt TTS when user speaks |
| Backchannel Filler | Pre-synthesized filler phrases ("mm-hmm", "I see") |

**WebSocket Endpoint:**
- `/ws/voice/{tenant_id}/{session_id}` - Bidirectional real-time voice
  - Client sends: Binary frames (raw PCM 16-bit, 16kHz mono) + JSON control messages
  - Server sends: Binary frames (TTS audio) + JSON text frames (transcripts, status)

### 2.5 Frontend (:3000)

**Technology:** Next.js 14, React 18, TypeScript, Tailwind CSS

**Key Dependencies:**
| Package | Purpose |
|---------|---------|
| `@tanstack/react-query` | Data fetching and caching |
| `zustand` | State management |
| `react-hook-form` + `zod` | Form handling and validation |
| `recharts` | Charts and analytics visualization |
| `framer-motion` | Animations |
| `@radix-ui/*` | Accessible UI components |
| `lucide-react` | Icon library |

---

## 3. Data Flow: Text Chat

```
User Message
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  1. API Gateway (:8000)                                          │
│     - JWT validation (cookie or Bearer token)                    │
│     - Tenant resolution from JWT claims                          │
│     - Rate limit check (Redis sliding window)                    │
│     - Plan limit enforcement (agent slots, message quotas)       │
│     - Strip forbidden fields from chat body (TC-E04)             │
│     - Forward to AI Orchestrator via reverse proxy               │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  2. AI Orchestrator (:8002)                                      │
│                                                                  │
│  Pre-LLM Pipeline:                                               │
│  ├── Session expiry check                                        │
│  ├── Input sanitization                                          │
│  ├── Emergency bypass (TC-E01): healthcare keywords -> 911       │
│  ├── Jailbreak detection (TC-B04/B05)                            │
│  ├── ML Moderation (OpenAI API -> detoxify -> regex)             │
│  ├── Intent detection                                            │
│  ├── Playbook routing (PlaybookEngine state machine)             │
│  ├── Guardrail check (blocked keywords, profanity)               │
│  ├── Short-term memory load (Redis: session:memory:{sid})        │
│  ├── Session summary load (Redis: session:summary:{sid})         │
│  ├── PII pseudonymization (Redis: pii_ctx:{sid}, 2h TTL)         │
│  ├── RAG context retrieval (pgvector similarity search)          │
│  ├── System prompt construction                                  │
│  ├── Tool schema loading                                         │
│  └── Semantic cache check (embedding similarity >= 0.92)         │
│                                                                  │
│  LLM Tool Loop (max 3 iterations):                               │
│  ├── LLM call (with circuit breaker + timeout)                   │
│  ├── Filter unauthorized tool calls                              │
│  ├── High-risk tool confirmation gate                            │
│  ├── PII restore in tool arguments                               │
│  ├── Tool execution via MCP Server                               │
│  ├── Credential scrubbing from error messages                    │
│  └── PII re-anonymize tool results                               │
│                                                                  │
│  Post-LLM Pipeline:                                              │
│  ├── Receipt summary for high-risk tool actions                  │
│  ├── Output guardrails (PII restore, length cap, disclaimer)     │
│  ├── Professional claim prevention (TC-E02)                      │
│  ├── Fallback escalation check (3 consecutive -> escalate)       │
│  ├── Semantic cache store (if eligible)                          │
│  ├── ConversationTrace persist                                   │
│  ├── Memory persist (short-term + LTM extraction)                │
│  ├── Auto-summarization (every 18 turns)                         │
│  ├── DB message persist                                          │
│  ├── Analytics update                                            │
│  └── Token budget record                                         │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  3. Response Delivery                                            │
│     - Streaming via SSE or WebSocket                              │
│     - PII restoration in streaming chunks                         │
│     - Usage metering (messages, chat units)                       │
│     - Webhook dispatch (if configured)                            │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. Data Flow: Voice

```
Caller (Twilio SIP/RTP)
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  1. Voice Pipeline (:8003)                                       │
│     - Receive audio frames via WebSocket                         │
│     - Energy-based VAD (Voice Activity Detection)                │
│     - Buffer frames until end-of-utterance                       │
│     - Barge-in detection: cancel TTS if user speaks              │
│     - Pre-recorded greeting playback (cost-free)                 │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  2. STT Service                                                  │
│     - Provider: Gemini (default), OpenAI, or Deepgram            │
│     - Output: Transcript + confidence score                      │
│     - Guardrail: confidence < 0.6 -> ask user to repeat          │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  3. AI Orchestrator (:8002)                                      │
│     - Same pipeline as text chat                                 │
│     - Voice-specific system prompt (no markdown, 3-sentence max) │
│     - Multi-lingual IVR protocol (EN/FR/ZH/ES)                   │
│     - Voice guardrails (GG-01 through GG-16)                     │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  4. TTS Service                                                  │
│     - Provider: Cartesia (default), Google, ElevenLabs, OpenAI   │
│     - Sentence-by-sentence synthesis for low latency             │
│     - Pre-synthesized backchannel fillers ($0 runtime cost)      │
│     - Audio streaming back to client via WebSocket               │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
Caller receives audio response
```

---

## 5. Database Schema

### 5.1 PostgreSQL Tables (23+ models)

The database uses PostgreSQL 16 with the `pgvector` extension for semantic search. Tables are created by SQLAlchemy at service startup.

#### API Gateway Schema

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `tenants` | Multi-tenant organization | id, name, slug, plan, stripe_customer_id, subscription_status |
| `users` | User accounts within tenants | id, tenant_id, email, hashed_password, role, is_email_verified |
| `api_keys` | Programmatic access keys | id, tenant_id, user_id, key_hash, key_prefix, scopes, agent_id |
| `webhooks` | Outbound webhook subscriptions | id, tenant_id, url, events, secret (HMAC-SHA256) |
| `tenant_usage` | Monthly usage tracking | tenant_id, agent_count, current_month_sessions/messages/chat_units/tokens/voice_minutes, total_cost_usd |

#### AI Orchestrator Schema

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `agents` | AI agent definitions | id, tenant_id, name, business_type, system_prompt, voice_enabled, llm_config, tools |
| `sessions` | Conversation sessions | id, tenant_id, agent_id, customer_identifier, channel, status, turn_count |
| `messages` | Individual conversation messages | id, session_id, tenant_id, role, content, tool_calls, tokens_used, latency_ms |
| `agent_analytics` | Daily usage analytics | id, tenant_id, agent_id, date, total_sessions, total_messages, avg_response_latency_ms, estimated_cost_usd |
| `message_feedback` | User/operator feedback | id, message_id, session_id, rating, labels, ideal_response, correction_reason |
| `agent_playbooks` | Conversation playbooks | id, agent_id, name, intent_triggers, instructions, tone, scenarios |
| `agent_guardrails` | Per-agent content policies | id, agent_id, blocked_keywords, profanity_filter, pii_redaction, pii_pseudonymization |
| `agent_documents` | Knowledge base documents | id, agent_id, name, file_type, chunk_count, embedding (768-dim vector), status |
| `agent_document_chunks` | Document chunks for RAG | id, doc_id, content, embedding (768-dim vector), chunk_index |
| `playbook_executions` | Playbook state machine state | id, session_id, playbook_id, current_step_id, variables, history |
| `agent_tools` | Agent-specific tool definitions | id, agent_id, name, connector_type, input_schema, output_schema, config |
| `agent_variables` | Agent variables (global/local) | id, agent_id, name, scope, data_type, default_value |
| `escalation_attempts` | Human escalation audit trail | id, tenant_id, session_id, connector_type, status, ticket_id |
| `conversation_traces` | Full LLM call artifacts | id, session_id, turn_index, system_prompt, messages_sent, tool_calls, guardrail_actions, final_response |
| `prompt_versions` | Immutable prompt snapshots | id, agent_id, version_number, content, environment, is_active |
| `prompt_ab_tests` | A/B test experiments | id, agent_id, version_a_id, version_b_id, traffic_split_percent, status |
| `eval_cases` | Golden dataset entries | id, agent_id, input_text, expected_intent, expected_tools, rubric |
| `eval_runs` | Batch evaluation runs | id, agent_id, trigger, status, pass_rate, avg_composite_score |
| `eval_scores` | Per-case LLM-as-judge scores | id, run_id, case_id, relevance_score, accuracy_score, composite_score |
| `agent_templates` | Pre-built agent templates | id, key, name, category |
| `template_versions` | Template version snapshots | id, template_id, version, system_prompt_template |
| `template_variables` | Template variable definitions | id, template_id, key, type, default_value |
| `template_playbooks` | Template playbook definitions | id, template_version_id, name, trigger_condition, flow_definition |
| `template_tools` | Template tool definitions | id, template_version_id, tool_name, required_config_schema |
| `agent_template_instances` | Template instantiation records | id, tenant_id, agent_id, template_version_id, variable_values |
| `audit_logs` | Compliance audit trail | id, user_id, tenant_id, action, resource_type, details, ip_address |

#### MCP Server Schema

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `mcp_tools` | Tool definitions per tenant | id, tenant_id, name, category, input_schema, output_schema, endpoint_url, auth_config, is_builtin |
| `mcp_tool_executions` | Tool execution records | id, tenant_id, tool_id, session_id, status, input_data, output_data, duration_ms |
| `knowledge_bases` | RAG knowledge base containers | id, tenant_id, agent_id, name, description |
| `knowledge_documents` | Knowledge base documents | id, kb_id, tenant_id, title, content, embedding (768-dim vector), content_type |

### 5.2 Database Initialization

The `shared/db/init.sql` script runs on first PostgreSQL startup:

```sql
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pgvector for knowledge base embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Create audit_logs table
CREATE TABLE IF NOT EXISTS audit_logs (...);
```

All other tables are created by SQLAlchemy `create_all()` during service startup.

### 5.3 Row-Level Security (RLS)

PostgreSQL RLS policies enforce tenant isolation at the database layer. Each tenant can only access its own data. The API Gateway sets the RLS context from JWT claims on every request.

---

## 6. Redis Usage

Redis 7 serves as the caching and session layer with the following key patterns:

### 6.1 Key Patterns

| Key Pattern | Purpose | TTL |
|-------------|---------|-----|
| `session:memory:{session_id}` | Short-term conversation memory (Redis List) | 7 days |
| `session:summary:{session_id}` | LLM-generated session summary | 7 days |
| `pii_ctx:{session_id}` | PII pseudonymization context (real <-> pseudo mappings) | 2 hours |
| `customer:ltm:{tenant_id}:{customer_id}` | Long-term customer memory | Persistent |
| `playbook_state:{session_id}` | PlaybookEngine state machine state | 24 hours |
| `sem_cache:{tenant_id}:{agent_id}` | Semantic cache (embedding-based) | 1 hour |
| `ratelimit:tenant:{tenant_id}:{minute}` | Rate limiting counters | 2 minutes |
| `ratelimit:ip:{ip}:{minute}` | Unauthenticated rate limiting | 2 minutes |
| `session:fallbacks:{session_id}` | Consecutive fallback counter for escalation | Session lifetime |
| `otp:{email}` | Email verification OTP codes | 10 minutes |
| `password_reset:{token}` | Password reset tokens | 1 hour |
| `pending_activation:{email}` | Pending account activations | 24 hours |
| `corrections:{agent_id}` | Operator corrections for learning | Persistent |
| `tool_rate:{tenant_id}:{tool_name}` | Per-tool rate limiting (sorted set) | 60 seconds |

### 6.2 Redis Configuration

```
--maxmemory 512mb
--maxmemory-policy allkeys-lru
--appendonly yes
```

### 6.3 Semantic Cache Details

- **Storage:** Redis Hash per (tenant, agent) bucket
- **Embedding:** `sentence-transformers/all-MiniLM-L6-v2` (384-dim)
- **Similarity:** Cosine similarity, threshold >= 0.92
- **Max entries:** 500 per bucket (FIFO eviction, deletes oldest 50 when full)
- **Eligibility:** No tool calls, no PII tokens, no guardrail actions triggered
- **Bypass:** Disabled when `pii_pseudonymization` is enabled (prevents cross-session leakage)

---

## 7. Stripe Integration

### 7.1 Billing Model

AscenAI2 uses a **chat equivalent** billing model where all usage is normalized to a single unit:

- 1 text message = 1 chat equivalent
- 1 voice minute = 100 chat equivalents
- 1 chat unit = 10 text messages

### 7.2 Plan Structure

| Plan | Price/Agent | Chat Equivalents | Voice Minutes |
|------|-------------|-----------------|---------------|
| Starter | $49/mo | 20,000 | 0 |
| Growth | $99/mo | 80,000 | 1,500 |
| Business | $199/mo | 170,000 | 3,500 |
| Enterprise | Custom | Custom | Custom |

### 7.3 Stripe Integration Points

| Integration | Endpoint | Purpose |
|-------------|----------|---------|
| Checkout Session | `POST /api/v1/billing/create-checkout-session` | Create subscription |
| Agent Slot Session | `POST /api/v1/billing/create-agent-slot-session` | Purchase additional agent |
| Portal Session | `POST /api/v1/billing/portal-session` | Stripe customer portal |
| Invoice List | `GET /api/v1/billing/invoices` | List recent invoices |
| Billing Webhook | `POST /api/v1/billing/webhook` | Handle Stripe events |

### 7.4 Webhook Events Handled

| Event | Action |
|-------|--------|
| `checkout.session.completed` | Activate tenant, set plan, grant agent slots |
| `customer.subscription.created` | Update subscription status and agent count |
| `customer.subscription.updated` | Sync plan changes and agent slots |
| `invoice.paid` | Ensure tenant is active, grant minimum 1 slot |

### 7.5 Overage Calculation

When usage exceeds plan limits:
- Overage rate: $0.002 per chat equivalent
- Voice overage is included in the chat equivalent pool (1 min = 100 equivalents)

---

## 8. Security Architecture

### 8.1 Authentication

- **JWT tokens:** Access tokens (short-lived) and refresh tokens (long-lived)
- **Cookie-based:** HttpOnly, Secure (non-dev), SameSite=Lax cookies
- **API keys:** SHA-256 hashed, scoped permissions, optional agent-specific
- **WebSocket auth:** JWT via query parameter or Authorization header

### 8.2 PII Protection

- **Pseudonymization:** Reversible pseudo-values (not irreversible redaction)
- **Detection:** Presidio NLP engine with regex fallback
- **Flow:** Detect -> Replace -> LLM processes -> Restore -> Deliver
- **Supported types:** Email, phone, credit card, SIN, SSN

### 8.3 Guardrail Layers

1. **Pre-LLM:** Emergency bypass, jailbreak detection, ML moderation, input guardrails
2. **LLM-level:** Role injection stripping, voice-specific system prompts
3. **Post-LLM:** PII restoration, output guardrails, professional claim prevention, credential scrubbing
4. **Session-level:** Fallback escalation, tool confirmation gate, tool loop cap

### 8.4 Rate Limiting

- **Authenticated:** 300 requests/minute per tenant
- **Unauthenticated:** 30 requests/minute per IP
- **Per-tool:** Configurable per tool (default 60/minute)
- **Implementation:** Redis sorted sets with atomic Lua scripts

### 8.5 Prompt Injection Protection

- System prompt fields stripped from client chat requests (TC-E04)
- Role injection patterns stripped from user input
- PII pseudonymization prevents data leakage in prompts
- Credential scrubbing on tool error messages

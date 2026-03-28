# AscenAI2 — Production Architecture Documentation

> Version: 2.0 | Branch: `claude/ai-agent-mcp-platform-dpseU`

---

## 1. Application Overview

### 1.1 Purpose

AscenAI2 is a **production-grade, multi-tenant AI Agent Platform** enabling businesses to deploy intelligent conversational agents across text and voice channels. It provides agent creation, knowledge base management, tool integration, guardrails, PII protection, compliance controls, billing, and analytics — all within a strict multi-tenant security boundary.

### 1.2 Target Users

| User Type | Core Needs |
|---|---|
| Business Operators | Agent builder, analytics dashboard, billing management |
| Developers | REST API, WebSocket, API keys, embed widget, webhooks |
| End Customers | Low-latency chat and voice responses |
| Platform Admins | Compliance controls, tenant management |

### 1.3 Functional Requirements

| ID | Requirement |
|---|---|
| FR-01 | Multi-turn text chat with streaming and session memory |
| FR-02 | Voice channel (STT → LLM → TTS) with sub-200ms target |
| FR-03 | Tool calling via MCP server (HTTP tools + built-in integrations) |
| FR-04 | RAG with hybrid search, reranking, and source citations |
| FR-05 | Guardrails: blocked keywords, profanity, PII, jailbreak, emergency, toxicity |
| FR-06 | PII pseudonymization (reversible, per-session, Presidio-backed) |
| FR-07 | Declarative playbook flows (state machine execution) |
| FR-08 | Per-tenant token budget and plan-based limits |
| FR-09 | GDPR erasure, prompt versioning, A/B testing |
| FR-10 | Full conversation trace logging and replay |

### 1.4 Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-01 | Chat API P99 first-token latency | < 1.5 s |
| NFR-02 | Voice end-to-end latency | < 200 ms |
| NFR-03 | Availability | 99.9% monthly |
| NFR-04 | Horizontal scaling | Linear to 10× base |
| NFR-05 | GDPR erasure SLA | 30 days |
| NFR-06 | Zero cross-tenant data leakage | Enforced at DB + app layers |

---

## 2. System Architecture

### 2.1 System Context

```mermaid
C4Context
  title AscenAI2 System Context
  Person(op, "Business Operator", "Configures agents via dashboard")
  Person(dev, "Developer", "Integrates via REST/WebSocket")
  Person(cust, "End Customer", "Chats with AI agents")

  System_Boundary(p, "AscenAI2 Platform") {
    System(platform, "AscenAI2", "Multi-tenant AI Agent Platform")
  }

  System_Ext(gemini, "Google Gemini", "LLM + STT")
  System_Ext(openai, "OpenAI", "LLM / Whisper / TTS")
  System_Ext(cartesia, "Cartesia", "TTS <100ms")
  System_Ext(stripe, "Stripe", "Payments")
  System_Ext(twilio, "Twilio", "SMS")
  System_Ext(sentry, "Sentry", "Errors")
  System_Ext(otel, "OpenTelemetry", "Tracing")

  Rel(op, platform, "HTTPS Dashboard")
  Rel(dev, platform, "REST API / WebSocket")
  Rel(cust, platform, "Chat widget / Voice")
  Rel(platform, gemini, "LLM inference + STT")
  Rel(platform, openai, "Fallback LLM / Whisper")
  Rel(platform, cartesia, "TTS synthesis")
  Rel(platform, stripe, "Billing")
  Rel(platform, twilio, "SMS / WhatsApp")
  Rel(platform, sentry, "Error reporting")
  Rel(platform, otel, "Distributed traces")
```

### 2.2 Component Architecture

```mermaid
graph TB
  subgraph Clients
    FE["Next.js Dashboard :3000"]
    WC["Web Chat Widget"]
    CH["WhatsApp / SMS / Slack / Email"]
  end

  subgraph GW["API Gateway :8000"]
    AUTH["JWT + API Key Auth"]
    RL["Rate Limiter (Redis)"]
    PROX["Reverse Proxy + Plan Enforcer"]
    CHAN["Channel Webhooks"]
  end

  subgraph OR["AI Orchestrator :8002"]
    ORCH["Orchestrator Engine"]
    PB["Playbook Engine"]
    LLM["LLM Client (Gemini/OpenAI/Vertex)"]
    MR["Model Router"]
    MEM["Memory Manager"]
    PII["PII Service (Presidio)"]
    GRD["Guardrails + Moderation"]
    TL["Trace Logger"]
    SC["Semantic Cache"]
    PM["Prompt Manager"]
    EV["Eval Service"]
  end

  subgraph MCP["MCP Server :8001"]
    TR["Tool Registry"]
    TE["Tool Executor"]
    RAG["RAG Service (Hybrid)"]
    DI["Document Indexer"]
  end

  subgraph VP["Voice Pipeline :8003"]
    STT["STT (Gemini/Deepgram)"]
    TTS["TTS (Cartesia/ElevenLabs)"]
  end

  subgraph Data
    PG[("PostgreSQL 16\n(RLS enabled)")]
    RD[("Redis 7")]
    QD[("Qdrant 1.11\nVector DB")]
  end

  FE & WC & CH --> GW
  GW --> OR & MCP
  OR --> MCP
  OR --> LLM
  VP --> OR
  OR & MCP & GW --> PG & RD
  MCP --> QD
```

### 2.3 Chat Request Flow (Non-Streaming)

```mermaid
sequenceDiagram
  participant C as Client
  participant GW as API Gateway
  participant OR as Orchestrator
  participant SC as Semantic Cache
  participant MCP as MCP Server
  participant LLM as LLM Provider
  participant DB as PostgreSQL
  participant RD as Redis

  C->>GW: POST /api/v1/chat {message}
  GW->>GW: Auth + rate limit check
  GW->>OR: Proxy request

  OR->>SC: Check semantic cache (cosine >= 0.92?)
  SC-->>OR: Cache hit OR miss

  alt Cache Miss
    OR->>DB: Load agent + guardrails + playbook state
    OR->>RD: Load conversation history (20 turns)
    OR->>OR: Emergency + jailbreak + injection checks
    OR->>OR: ML Moderation (input)
    OR->>MCP: Hybrid RAG retrieval (BM25 + vector + rerank)
    OR->>OR: PII anonymize message (Presidio)
    OR->>OR: PromptManager.get_active_prompt() [version + A/B]
    OR->>RD: Check daily token budget

    loop Tool Loop (max 3)
      OR->>LLM: Complete (model selected by ModelRouter)
      LLM-->>OR: Response (tool_calls OR final)
      OR->>OR: Validate + de-tokenize tool args
      OR->>MCP: Execute tools
      MCP-->>OR: Tool results (re-anonymized)
    end

    OR->>OR: parse_envelope() + restore PII tokens
    OR->>OR: apply_output_guardrails() + ML moderation (output)
    OR->>DB: Persist messages + ConversationTrace
    OR->>RD: Update memory + token budget
    OR->>OR: maybe_summarize() if > 18 turns
    OR->>OR: extract_long_term_memory() if customer_identifier set
    OR->>SC: Cache response if cacheable
  end

  OR-->>GW: ChatResponse
  GW-->>C: 200 OK
```

### 2.4 Playbook Execution Flow

```mermaid
sequenceDiagram
  participant C as Client
  participant OR as Orchestrator
  participant PB as PlaybookEngine
  participant RD as Redis
  participant DB as PostgreSQL
  participant MCP as MCP Server

  C->>OR: POST /chat {message}
  OR->>RD: Check playbook_state:{session_id}

  alt Active Playbook
    OR->>PB: advance(session_id, user_input)
    PB->>RD: Load state (variables, current_step_id)

    alt WaitInput Step
      PB->>PB: validate input (regex if configured)
      PB->>PB: store in variables[field_name]
      PB->>PB: advance to next_step_id
    else ToolStep
      PB->>MCP: Execute tool with mapped args
      MCP-->>PB: Result
      PB->>PB: Store in variables[output_variable]
    else ConditionStep
      PB->>PB: safe_eval(expression, variables)
      PB->>PB: Branch to then_step OR else_step
    else LLMStep
      PB->>LLM: Complete with constrained prompt
      LLM-->>PB: Structured output
    else EndStep
      PB->>PB: Mark playbook complete
    end

    PB->>RD: Save updated state
    PB->>DB: Checkpoint execution
    PB-->>OR: {response, awaiting_input, complete}
  else No Active Playbook
    OR->>OR: Check trigger_keywords → auto-start?
    OR->>OR: Regular LLM pipeline
  end

  OR-->>C: Response
```

---

## 3. Data Architecture

### 3.1 Core Database Schema

```mermaid
erDiagram
  tenants {
    uuid id PK
    string name
    string slug UK
    string business_type
    string plan
    bool is_active
    datetime trial_ends_at
  }

  users {
    uuid id PK
    uuid tenant_id FK
    string email UK
    string hashed_password
    string role
    bool is_active
  }

  agents {
    uuid id PK
    uuid tenant_id FK
    string name
    text system_prompt
    bool voice_enabled
    json tools
    json knowledge_base_ids
    json llm_config
    bool is_active
  }

  sessions {
    uuid id PK
    uuid tenant_id FK
    uuid agent_id FK
    string customer_identifier
    string channel
    string status
    json metadata
  }

  messages {
    uuid id PK
    uuid session_id FK
    uuid tenant_id FK
    string role
    text content
    int tokens_used
    int latency_ms
    string guardrail_triggered
  }

  prompt_versions {
    uuid id PK
    uuid agent_id FK
    uuid tenant_id FK
    int version
    text content
    string description
    string environment
    bool is_active
    int ab_traffic_percent
    string ab_variant
    uuid created_by FK
  }

  playbook_definitions {
    uuid id PK
    uuid tenant_id FK
    uuid agent_id FK
    string name
    int version
    json definition
    json trigger_keywords
    bool is_active
  }

  playbook_executions {
    uuid id PK
    uuid session_id FK
    uuid playbook_id FK
    uuid tenant_id FK
    string status
    string current_step_id
    json variables
    json step_history
    datetime started_at
    datetime completed_at
  }

  conversation_traces {
    uuid id PK
    string session_id FK
    uuid tenant_id FK
    uuid agent_id FK
    int turn_index
    text system_prompt
    json memory_snapshot
    json retrieved_chunks
    json messages_sent
    string llm_provider
    string raw_llm_response
    json tool_calls
    json guardrail_actions
    text final_response
    json latency_breakdown
    int tokens_used
  }

  eval_cases {
    uuid id PK
    uuid tenant_id FK
    uuid agent_id FK
    string name
    text input_message
    json expected_tool_calls
    json expected_response_contains
    text rubric
    float min_score
  }

  eval_runs {
    uuid id PK
    uuid tenant_id FK
    uuid agent_id FK
    string triggered_by
    string commit_sha
    string status
    int total_cases
    int passed_cases
    float pass_rate
    bool blocking
  }

  eval_scores {
    uuid id PK
    uuid eval_run_id FK
    uuid eval_case_id FK
    text actual_response
    float score
    bool passed
    json score_breakdown
    text llm_judge_reasoning
  }

  tenants ||--o{ users : ""
  tenants ||--o{ agents : ""
  tenants ||--o{ sessions : ""
  agents ||--o{ sessions : ""
  sessions ||--o{ messages : ""
  agents ||--o{ prompt_versions : ""
  agents ||--o{ playbook_definitions : ""
  sessions ||--o{ playbook_executions : ""
  sessions ||--o{ conversation_traces : ""
  agents ||--o{ eval_cases : ""
  agents ||--o{ eval_runs : ""
```

### 3.2 Redis Key Reference

| Key Pattern | Type | TTL | Purpose |
|---|---|---|---|
| `rate_limit:{tenant_id}:{minute}` | String | 60s | Token-bucket rate limiting |
| `session:mem:{session_id}` | List (JSON) | 24h | Short-term conversation history |
| `session:summary:{session_id}` | String | 24h | LLM-compressed conversation summary |
| `summary_lock:{session_id}` | String | 30s | SETNX lock prevents duplicate summarization |
| `session:fallbacks:{session_id}` | String | 1h | Consecutive fallback counter |
| `pii_ctx:{session_id}` | String (JSON) | 1h | PII token ↔ value map |
| `token_budget:{tenant_id}:{date}` | String | 25h | Daily LLM token counter |
| `active_prompt:{agent_id}:{env}` | String (JSON) | 5min | Cached active prompt version |
| `tool_schemas:{agent_id}` | String (JSON) | 5min | Cached MCP tool schemas |
| `semantic_cache:{tenant_id}:{agent_id}:embeddings` | Hash | 1h | Cached query embeddings |
| `playbook_state:{session_id}` | String (JSON) | 24h | Active playbook execution state |
| `customer:ltm:{tenant_id}:{customer_id}` | String (JSON) | 30d | Long-term customer memory |
| `idempotency:{key}` | String | 5min | Chat idempotency dedup |
| `document_index_queue:{tenant_id}` | List | — | Background indexing job queue |
| `doc_status:{doc_id}` | String | 24h | Document indexing status |

---

## 4. Technology Stack

| Layer | Technology | Justification |
|---|---|---|
| **Frontend** | Next.js 14 (App Router) | SSR, TypeScript-first, Vercel ecosystem |
| **State** | Zustand + React Query | Minimal boilerplate; server state caching |
| **Styling** | TailwindCSS + Radix UI | Accessible headless components; no CSS bloat |
| **API Framework** | FastAPI | Native async; OpenAPI auto-gen; Pydantic |
| **ORM** | SQLAlchemy 2.0 async | asyncpg driver; type-safe; Alembic migrations |
| **Auth** | python-jose + passlib | HS256 JWT; bcrypt passwords |
| **LLM** | google-genai + openai SDK | Native async; multi-provider circuit breaker |
| **PII** | Presidio + spaCy | 50+ entity types; reversible pseudonymization |
| **Logging** | structlog (JSON) | Structured output; processor pipeline |
| **Metrics** | prometheus-fastapi-instrumentator | Zero-config RED metrics |
| **Primary DB** | PostgreSQL 16 | ACID; RLS; JSONB; battle-tested |
| **Cache** | Redis 7 | Sub-ms latency; atomic ops; TTL |
| **Vector DB** | Qdrant 1.11 | Purpose-built; payload filter; Rust core |
| **Containers** | Docker + Compose | Universal reproducibility |
| **CI/CD** | GitHub Actions | OIDC; matrix builds; no extra infra |
| **Tracing** | OpenTelemetry (vendor-neutral) | Supports Jaeger/Honeycomb/Tempo |

---

## 5. Security Architecture

### RBAC Matrix

| Permission | owner | admin | viewer |
|---|---|---|---|
| Create/delete agents | ✅ | ✅ | ❌ |
| Billing + team management | ✅ | ❌ | ❌ |
| API key management | ✅ | ✅ | ❌ |
| View analytics | ✅ | ✅ | ✅ |
| GDPR erasure | ✅ | ❌ | ❌ |

### Encryption Reference

| Data | Method |
|---|---|
| Passwords | bcrypt (12 rounds) |
| API keys (stored) | SHA-256 one-way |
| Tool credentials | AES-256 Fernet |
| JWT signing | HMAC-SHA256 (min 32-char key) |
| PII in LLM context | Reversible `{{PII_TYPE_N}}` tokens |
| Data in transit | TLS 1.2+ (Nginx termination) |

### OWASP Top 10 Mitigations

| Risk | Mitigation |
|---|---|
| Broken Access Control | `tenant_id` on every query + PostgreSQL RLS |
| Injection (SQL) | SQLAlchemy parameterized queries |
| Prompt Injection | `_ROLE_INJECTION_PATTERN` + `_JAILBREAK_PATTERN` + agents.py validation |
| Cryptographic Failures | Fernet encryption; bcrypt; SHA-256 for API keys |
| Security Misconfiguration | SECRET_KEY min-length validation at startup; CSP dev-only `unsafe-eval` |
| Credential Exposure | `_CREDENTIAL_SCRUB_PATTERN` in error messages; never log content |

---

## 6. DevOps & Deployment

### CI/CD Pipeline

```mermaid
graph LR
  subgraph "Every PR"
    L1["Ruff lint (4 services)"]
    L2["TypeScript + ESLint + Next build"]
    T1["pytest + testcontainers (api-gateway)"]
  end
  subgraph "Merge to main"
    D1["Docker build (all 5 images)"]
    E1["Eval gate (pass_rate >= 0.8)"]
    PUSH["Push to registry"]
  end
  subgraph "Deploy"
    ROLL["Rolling restart"]
    SMOKE["Health check probes"]
    RB["Auto-rollback on failure"]
  end
  L1 & L2 & T1 --> D1 --> E1 --> PUSH --> ROLL --> SMOKE --> RB
```

### Health Probes

| Endpoint | Type | Checks | K8s Use |
|---|---|---|---|
| `/health/startup` | Heavy | DB + Redis + MCP | startupProbe |
| `/health/ready` | Fast | DB + Redis | readinessProbe |
| `/health/live` | Minimal | Process alive | livenessProbe |
| `/health` | Summary | Status + versions | Uptime monitoring |

---

## 7. Testing Strategy

### Testing Pyramid

| Layer | Coverage | Tools |
|---|---|---|
| Unit | Guardrails, PII, playbook conditions, memory | pytest |
| Integration | DB CRUD, Redis ops, MCP→Qdrant | testcontainers |
| API | All endpoints with real services | httpx.AsyncClient |
| E2E | Full user journeys | Playwright |
| Performance | 100 concurrent users | Locust |
| Security | OWASP scan + dependency audit | OWASP ZAP + pip-audit |

### Critical Path Regression Checklist

- [ ] Register → login → JWT claims correct
- [ ] Text chat (sync + stream) returns valid response
- [ ] Session memory persists across 5 consecutive turns
- [ ] Summarization fires at turn 18, history trimmed to 4 turns
- [ ] Playbook starts on trigger keyword, advances through steps, completes
- [ ] RAG sources included in response with score > 0.7
- [ ] Blocked keyword → guardrail_triggered set, 0 tokens used
- [ ] Emergency bypass → instant hardcoded response, no LLM
- [ ] PII tokens never appear in final response or DB message content
- [ ] Prompt version A/B: ~50% sessions hit treatment over 100 requests
- [ ] ConversationTrace created with full system_prompt for every turn
- [ ] Eval gate blocks deploy if pass_rate < 0.8
- [ ] Cross-tenant isolation: Tenant A cannot read Tenant B's agents
- [ ] PostgreSQL RLS: direct DB query with wrong tenant_id returns 0 rows
- [ ] Semantic cache returns identical response for cosine similarity >= 0.92

---

## 8. Observability

### Structured Log Format

```json
{
  "timestamp": "2026-03-28T10:15:32.450Z",
  "level": "info",
  "event": "chat_response_generated",
  "session_id": "sess_xyz",
  "tenant_id": "tenant_abc",
  "latency_ms": 842,
  "tokens_used": 347,
  "tool_calls": 1,
  "prompt_version_id": "v12",
  "cache_hit": false,
  "pii_entity_types": ["PERSON", "PHONE_NUMBER"],
  "guardrail_actions": [],
  "trace_id": "4bf92f3577b34da6"
}
```

### Key Prometheus Metrics

| Metric | Alert Threshold |
|---|---|
| `http_request_duration_seconds` P99 | > 4s |
| `ascenai_pii_envelope_parse_failures_total` | > 5% of requests |
| `llm_circuit_breaker_state` | open (any) |
| `ascenai_eval_pass_rate` | < 0.8 |
| `ascenai_semantic_cache_hit_rate` | < 10% (indicates cache not working) |
| `ascenai_playbook_step_failures_total` | > 1% per step |
| `token_budget_exceeded_total` | Any > 0 (alert tenant) |

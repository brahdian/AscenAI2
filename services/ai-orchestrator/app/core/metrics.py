"""
Custom Prometheus metrics for the AI Orchestrator.

Covers business-critical signals that the generic FastAPI instrumentor misses:
  - LLM token consumption and cost proxy (by provider/model)
  - LLM call latency (p50/p95/p99)
  - Escalation outcomes (per connector, per status)
  - Tool execution counts and error rates
  - Session and message throughput
  - Circuit-breaker state changes
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

LLM_TOKENS = Counter(
    "ascenai_llm_tokens_total",
    "Total LLM tokens consumed",
    labelnames=["provider", "model", "type"],  # type: prompt | completion
)

LLM_LATENCY = Histogram(
    "ascenai_llm_latency_seconds",
    "LLM call latency (wall clock, including queue time)",
    labelnames=["provider", "model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

LLM_ERRORS = Counter(
    "ascenai_llm_errors_total",
    "LLM call failures",
    labelnames=["provider", "model", "error_type"],  # error_type: timeout|circuit_open|api_error
)

LLM_CIRCUIT_OPENS = Counter(
    "ascenai_llm_circuit_breaker_opens_total",
    "Number of times the LLM circuit breaker tripped open",
    labelnames=["provider"],
)

# ---------------------------------------------------------------------------
# Tool execution (MCP)
# ---------------------------------------------------------------------------

TOOL_EXECUTIONS = Counter(
    "ascenai_tool_executions_total",
    "MCP tool execution attempts",
    labelnames=["tool_name", "status"],  # status: success|error|circuit_open
)

TOOL_LATENCY = Histogram(
    "ascenai_tool_latency_seconds",
    "MCP tool execution latency",
    labelnames=["tool_name"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 15.0],
)

MCP_CIRCUIT_OPENS = Counter(
    "ascenai_mcp_circuit_breaker_opens_total",
    "Number of times the MCP circuit breaker tripped open",
)

# ---------------------------------------------------------------------------
# Escalation connectors
# ---------------------------------------------------------------------------

ESCALATION_ATTEMPTS = Counter(
    "ascenai_escalation_attempts_total",
    "Live-agent escalation attempts",
    labelnames=["connector_type", "status"],  # status: success|failed|deduplicated|skipped
)

ESCALATION_LATENCY = Histogram(
    "ascenai_escalation_latency_seconds",
    "Connector handoff latency",
    labelnames=["connector_type"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 15.0, 30.0],
)

# ---------------------------------------------------------------------------
# Sessions and messages
# ---------------------------------------------------------------------------

MESSAGES_PROCESSED = Counter(
    "ascenai_messages_processed_total",
    "Chat messages processed (non-escalation)",
    labelnames=["channel"],  # channel: text|voice|web
)

SESSIONS_CREATED = Counter(
    "ascenai_sessions_created_total",
    "New sessions started",
    labelnames=["channel"],
)

ACTIVE_SESSIONS = Gauge(
    "ascenai_active_sessions",
    "Currently active (non-closed) sessions",
)

FALLBACK_RESPONSES = Counter(
    "ascenai_fallback_responses_total",
    "Responses that triggered the fallback escalation counter",
    # agent_id intentionally omitted — unbounded cardinality would OOM Prometheus
)

# ---------------------------------------------------------------------------
# Context retrieval (RAG)
# ---------------------------------------------------------------------------

CONTEXT_RETRIEVALS = Counter(
    "ascenai_context_retrievals_total",
    "RAG context retrieval calls",
    labelnames=["status"],  # status: hit|miss|error
)

CONTEXT_ITEMS_RETURNED = Histogram(
    "ascenai_context_items_returned",
    "Number of context items returned per retrieval",
    buckets=[0, 1, 2, 3, 5, 10, 20],
)

# ---------------------------------------------------------------------------
# Observability — queue depths and contract validation
# ---------------------------------------------------------------------------

DOC_INDEX_QUEUE_DEPTH = Gauge(
    "ascenai_doc_index_queue_depth",
    "Current depth of the document indexing queue",
)

DOC_INDEX_DLQ_DEPTH = Gauge(
    "ascenai_doc_index_dlq_depth",
    "Current depth of the document indexing dead-letter queue",
)

CONTRACT_VALIDATION_ERRORS = Counter(
    "ascenai_contract_validation_errors_total",
    "HTTP 422 request validation errors (API contract mismatches)",
    labelnames=["path"],
)

# ---------------------------------------------------------------------------
# Zenith Compliance & Audit Metrics (Pillar 1, 2)
# ---------------------------------------------------------------------------

AUDIT_LOG_WRITES = Counter(
    "zenith_audit_log_writes_total",
    "Total audit log entries created",
    ["tenant_id", "action", "category"]
)

PII_REDACTED = Counter(
    "zenith_pii_redacted_total",
    "Total PII instances redacted from prompts and logs",
    ["tenant_id", "pii_type"]
)

DOCUMENT_ACCESSED = Counter(
    "zenith_document_accessed_total",
    "Total document accesses for RAG",
    ["tenant_id", "agent_id"]
)

# ---------------------------------------------------------------------------
# Zenith Cost Governance Metrics (Pillar 10)
# ---------------------------------------------------------------------------

LLM_COST_USD = Counter(
    "zenith_llm_cost_usd_total",
    "Total LLM cost in USD",
    ["tenant_id", "model", "agent_id"]
)

TOOL_COST_USD = Counter(
    "zenith_tool_cost_usd_total",
    "Total tool execution cost in USD",
    ["tenant_id", "tool_name", "agent_id"]
)

TENANT_QUOTA_EXCEEDED = Counter(
    "zenith_tenant_quota_exceeded_total",
    "Total times tenant exceeded plan limits",
    ["tenant_id", "limit_type"]
)

# ---------------------------------------------------------------------------
# Zenith Workflow & Determinism Metrics (Pillar 9)
# ---------------------------------------------------------------------------

WORKFLOW_EXECUTIONS = Counter(
    "zenith_workflow_executions_total",
    "Total workflow executions",
    ["tenant_id", "agent_id", "workflow_id", "status"]
)

WORKFLOW_NODE_EXECUTIONS = Counter(
    "zenith_workflow_node_executions_total",
    "Total workflow node executions",
    ["tenant_id", "workflow_id", "node_type", "status"]
)

WORKFLOW_RETRIES = Counter(
    "zenith_workflow_retries_total",
    "Total workflow node retries",
    ["tenant_id", "workflow_id"]
)

# ---------------------------------------------------------------------------
# Zenith SLO & Error Budget Metrics
# ---------------------------------------------------------------------------

SLO_ERROR_BUDGET_REMAINING = Gauge(
    "zenith_slo_error_budget_remaining_percent",
    "Remaining error budget for 99.9% SLO",
    ["service"]
)

ERROR_BUDGET_CONSUMPTION = Counter(
    "zenith_error_budget_consumption_total",
    "Total error budget consumed",
    ["service"]
)

# ---------------------------------------------------------------------------
# Zenith Metric Helpers
# ---------------------------------------------------------------------------

def record_llm_usage(model: str, tenant_id: str, agent_id: str, prompt_tokens: int, completion_tokens: int, cost_usd: float):
    """Record complete LLM usage with cost tracking"""
    LLM_TOKENS.labels(provider="openai", model=model, type="prompt").inc(prompt_tokens)
    LLM_TOKENS.labels(provider="openai", model=model, type="completion").inc(completion_tokens)
    LLM_COST_USD.labels(tenant_id=tenant_id, model=model, agent_id=agent_id).inc(cost_usd)


def record_workflow_execution(tenant_id: str, agent_id: str, workflow_id: str, status: str, duration: float):
    """Record workflow execution metrics"""
    WORKFLOW_EXECUTIONS.labels(tenant_id=tenant_id, agent_id=agent_id, workflow_id=workflow_id, status=status).inc()


def record_audit_log(tenant_id: str, action: str, category: str):
    """Record audit log creation"""
    AUDIT_LOG_WRITES.labels(tenant_id=tenant_id, action=action, category=category).inc()


def record_pii_redaction(tenant_id: str, pii_type: str, count: int = 1):
    """Record PII redaction events"""
    PII_REDACTED.labels(tenant_id=tenant_id, pii_type=pii_type).inc(count)


async def metrics_endpoint():
    """Prometheus /metrics endpoint with all Zenith metrics"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi import Response
    
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )

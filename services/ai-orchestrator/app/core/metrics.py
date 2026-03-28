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
    labelnames=["agent_id"],
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

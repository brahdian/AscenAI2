"""MCP Integration Layer — provider-agnostic action system.

Architecture:
  actions.py       — Canonical MCP action schemas (LLM-facing, provider-neutral)
  base.py          — BaseAdapter ABC + ActionRegistry
  errors.py        — Unified error types + provider error normalization
  adapters/        — One file per provider (Stripe, Twilio, Google Calendar …)
  webhooks/        — Webhook ingestion, signature verification, event normalization
"""

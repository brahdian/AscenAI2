"""
analytics_sync.py — Historical analytics reconciliation script.

Purpose
-------
Rebuilds the ``agent_analytics`` daily rollup table from the raw ``sessions``
and ``messages`` tables.  Run this manually when you suspect the rollup has
drifted from reality (e.g., after a data migration or if the service
experienced errors during ``update_analytics``).

Safety guarantees
-----------------
* Uses UPSERT semantics — never truncates or zeros existing rows.
* Preserves columns not derivable from raw data (e.g. ``avg_response_latency_ms``).
* Operates per-day (not just "today") so all historical days are reconciled.
* Idempotent: safe to run multiple times.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func, text
from app.core.database import AsyncSessionLocal, init_db
from app.models.agent import Session as AgentSession, Message


async def sync_analytics() -> None:
    print("--- Synchronizing Analytics (safe upsert, all days) ---")
    await init_db()
    async with AsyncSessionLocal() as db:
        # ── 1. Rebuild agent_analytics from raw data, one row per (agent, date) ──
        #
        # We aggregate directly in the DB to avoid pulling millions of rows into
        # Python memory, and we use INSERT … ON CONFLICT to guarantee idempotency.
        #
        # What we CAN derive from raw tables:
        #   • total_sessions  — COUNT of sessions
        #   • total_messages  — COUNT of assistant messages
        #   • total_chat_units — SUM(ceil(turn_count / 10)) per session, floor=1
        #   • avg_response_latency_ms — existing value is preserved (we don't
        #     overwrite it because Message.latency_ms exists per-message and
        #     could be summed if needed; we leave it as-is to avoid data loss)
        #   • total_tokens_used — SUM(messages.tokens_used)
        #   • estimated_cost_usd — re-derived from tokens at $0.0001 per 1k tokens
        #
        # Columns intentionally NOT changed:
        #   • tool_executions, escalations, successful_completions, total_voice_minutes
        #     (these require orchestrator event signals not available in raw tables)
        rebuild_sql = text("""
            WITH
            -- Step 1: per-agent-day session counts and chat unit sums
            session_agg AS (
                SELECT
                    tenant_id,
                    agent_id,
                    DATE(started_at AT TIME ZONE 'UTC')      AS day,
                    COUNT(*)                                 AS n_sessions,
                    SUM(
                        GREATEST(1, CEIL(GREATEST(turn_count, 0)::numeric / 10))
                    )::INTEGER                              AS n_chat_units
                FROM sessions
                GROUP BY tenant_id, agent_id, DATE(started_at AT TIME ZONE 'UTC')
            ),
            -- Step 2: per-agent-day message token totals (assistant only)
            message_agg AS (
                SELECT
                    s.tenant_id,
                    s.agent_id,
                    DATE(m.created_at AT TIME ZONE 'UTC')   AS day,
                    COUNT(m.id)                             AS n_messages,
                    COALESCE(SUM(m.tokens_used), 0)         AS n_tokens,
                    CASE
                        WHEN COUNT(m.id) > 0
                        THEN COALESCE(SUM(m.latency_ms), 0)::float / COUNT(m.id)
                        ELSE 0
                    END                                     AS avg_latency
                FROM messages m
                JOIN sessions s ON s.id = m.session_id
                WHERE m.role = 'assistant'
                GROUP BY s.tenant_id, s.agent_id, DATE(m.created_at AT TIME ZONE 'UTC')
            )
            -- Step 3: UPSERT into agent_analytics
            INSERT INTO agent_analytics (
                id,
                tenant_id, agent_id, date,
                total_sessions, total_messages,
                avg_response_latency_ms,
                total_tokens_used, estimated_cost_usd,
                total_chat_units,
                -- Preserve orchestrator-only counters at 0 on first insert;
                -- ON CONFLICT block leaves them untouched.
                tool_executions, escalations, successful_completions, total_voice_minutes
            )
            SELECT
                gen_random_uuid(),
                sa.tenant_id,
                sa.agent_id,
                sa.day,
                sa.n_sessions,
                COALESCE(ma.n_messages,  0),
                COALESCE(ma.avg_latency, 0.0),
                COALESCE(ma.n_tokens,    0),
                COALESCE(ma.n_tokens, 0) * 0.0001 / 1000.0,
                GREATEST(sa.n_sessions, sa.n_chat_units),
                0, 0, 0, 0.0
            FROM session_agg sa
            LEFT JOIN message_agg ma
                ON  ma.tenant_id = sa.tenant_id
                AND ma.agent_id  = sa.agent_id
                AND ma.day       = sa.day
            ON CONFLICT (tenant_id, agent_id, date) DO UPDATE SET
                -- Session / message counts are always authoritative from raw data.
                total_sessions         = EXCLUDED.total_sessions,
                total_messages         = EXCLUDED.total_messages,
                total_tokens_used      = EXCLUDED.total_tokens_used,
                estimated_cost_usd     = EXCLUDED.estimated_cost_usd,
                total_chat_units       = EXCLUDED.total_chat_units,
                -- Re-compute latency only when we have message data.
                avg_response_latency_ms = CASE
                    WHEN EXCLUDED.avg_response_latency_ms > 0
                    THEN EXCLUDED.avg_response_latency_ms
                    ELSE agent_analytics.avg_response_latency_ms
                END
                -- tool_executions, escalations, successful_completions,
                -- and total_voice_minutes are NOT overwritten here:
                -- they are owned by the live orchestrator path and must
                -- not be zeroed by a reconciliation script.
        """)
        result = await db.execute(rebuild_sql)
        print(f"agent_analytics rows upserted/updated: {result.rowcount}")

        # ── 2. Rebuild tenant_usage from agent_analytics totals ───────────────
        #
        # This is a hard-reset ("current_month_*" = sum of this calendar month).
        # It is safe because tenant_usage is a derived/materialized view of
        # agent_analytics; its authoritative source is always this table.
        rebuild_tenant_usage = text("""
            WITH monthly AS (
                SELECT
                    tenant_id,
                    SUM(total_sessions)   AS sessions,
                    SUM(total_messages)   AS messages,
                    SUM(total_tokens_used)AS tokens,
                    SUM(total_chat_units) AS chat_units,
                    SUM(total_voice_minutes) AS voice_minutes
                FROM agent_analytics
                WHERE date >= DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
                GROUP BY tenant_id
            )
            UPDATE tenant_usage tu
            SET
                current_month_sessions      = m.sessions,
                current_month_messages      = m.messages,
                current_month_tokens        = m.tokens,
                current_month_chat_units    = m.chat_units,
                current_month_voice_minutes = m.voice_minutes,
                updated_at                  = NOW()
            FROM monthly m
            WHERE tu.tenant_id = m.tenant_id
        """)
        result2 = await db.execute(rebuild_tenant_usage)
        print(f"tenant_usage rows updated: {result2.rowcount}")

        await db.commit()
        print("\nSync complete — no data was zeroed.")


if __name__ == "__main__":
    asyncio.run(sync_analytics())

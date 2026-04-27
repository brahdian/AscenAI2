import asyncio
import json
import re
from typing import Optional, TYPE_CHECKING

import structlog
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings

if TYPE_CHECKING:
    from .llm_client import LLMClient

logger = structlog.get_logger(__name__)

SESSION_MEMORY_PREFIX = "session:memory:"
SESSION_SUMMARY_PREFIX = "session:summary:"
CUSTOMER_MEMORY_PREFIX = "customer:memory:"
CUSTOMER_LTM_PREFIX = "customer:ltm:"
SUMMARY_LOCK_PREFIX = "summary_lock:"
MEMORY_TTL_SECONDS = 86400 * 7  # 7 days

# Configurable via env: number of turns that triggers summarization
SUMMARY_TRIGGER_TURNS: int = getattr(settings, "SUMMARY_TRIGGER_TURNS", 18)
# How many of the oldest turns to compress when threshold is hit
SUMMARY_COMPRESS_TURNS: int = 14
# How many recent turns to keep in the live window after summarization
SUMMARY_RETAIN_TURNS: int = 4
# Redis lock TTL (seconds)
SUMMARY_LOCK_TTL: int = 30
# Seconds to wait for another process to finish summarizing before giving up
SUMMARY_LOCK_WAIT_SECONDS: float = 2.0

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

SUMMARIZATION_PROMPT = """You are a conversation summarizer. Compress the following conversation turns into a dense summary that preserves ALL decision-relevant information.

PRESERVE:
- Names, emails, phone numbers, booking references, order IDs
- Decisions made (e.g. "user chose Plan B", "appointment booked for March 15")
- Open questions or unresolved intents
- Tool results (e.g. "payment confirmed: TXN-4821")
- Current topic/context

DISCARD:
- Pleasantries and filler
- Repeated questions
- Already-resolved small talk

Return JSON: {"summary": "...", "entities": {"names": [], "references": [], "open_intents": []}}"""

MEMORY_EXTRACTION_PROMPT = """Extract stable, useful facts about this customer from the conversation.
Only extract facts that will be useful in FUTURE conversations.
Confidence threshold: 0.7

Extract: name, email, phone, preferences, account_type, location, open_issues
Skip: transient statements, greetings, one-time questions

Return JSON or null if nothing useful:
{"name": null, "email": null, "phone": null, "preferences": [], "facts": {}}"""

# Patterns that indicate prompt-injection or poisoning attempts
_INJECTION_PATTERNS = re.compile(
    r"(ignore (previous|all|above)|system prompt|you are now|pretend to be|"
    r"disregard instructions|override|jailbreak|<script|javascript:|base64)",
    re.IGNORECASE,
)


class MemoryManager:
    """
    Manages short-term (Redis) and long-term (Redis + PostgreSQL) memory for sessions.

    Short-term memory: A sliding window of the last N messages per session,
    stored in a Redis list for fast retrieval.

    Long-term memory: Customer preferences and interaction history stored
    in both Redis (for fast reads) and PostgreSQL (for cross-session context).

    Auto-summarization: When session history exceeds SUMMARY_TRIGGER_TURNS,
    the oldest SUMMARY_COMPRESS_TURNS turns are compressed via LLM into a
    dense summary, guarded by a Redis SETNX lock to prevent race conditions.
    """

    def __init__(self, redis_client: aioredis.Redis, db: AsyncSession):
        self.redis = redis_client
        self.db = db
        self.window_size = settings.MEMORY_WINDOW_SIZE

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def _session_key(self, session_id: str) -> str:
        return f"{SESSION_MEMORY_PREFIX}{session_id}"

    def _summary_key(self, session_id: str) -> str:
        return f"{SESSION_SUMMARY_PREFIX}{session_id}"

    def _customer_key(self, tenant_id: str, customer_id: str) -> str:
        return f"{CUSTOMER_MEMORY_PREFIX}{tenant_id}:{customer_id}"

    def _ltm_key(self, tenant_id: str, customer_identifier: str) -> str:
        return f"{CUSTOMER_LTM_PREFIX}{tenant_id}:{customer_identifier}"

    def _lock_key(self, session_id: str) -> str:
        return f"{SUMMARY_LOCK_PREFIX}{session_id}"

    # ------------------------------------------------------------------
    # Short-term memory
    # ------------------------------------------------------------------

    async def get_short_term_memory(self, session_id: str) -> list[dict]:
        """
        Retrieve the recent messages for a session from Redis.
        Returns a list of message dicts ordered oldest to newest.
        Also injects the session summary (if any) as the first system message
        so the orchestrator can use it without a separate call.
        """
        key = self._session_key(session_id)
        try:
            # Cap at the 50 most-recent messages to prevent large session histories
            # from bloating the LLM context window (list is stored oldest→newest).
            raw_messages = await self.redis.lrange(key, -50, -1)
            messages = []
            for raw in raw_messages:
                try:
                    messages.append(json.loads(raw))
                except json.JSONDecodeError:
                    logger.warning("memory_decode_error", session_id=session_id)
            return messages
        except Exception as exc:
            logger.error("get_short_term_memory_error", session_id=session_id, error=str(exc))
            return []

    async def get_short_term_memory_with_summary(
        self, session_id: str
    ) -> tuple[list[dict], Optional[str]]:
        """
        Retrieve both the current message window and any stored summary.
        Returns (messages, summary_text_or_None).
        """
        messages = await self.get_short_term_memory(session_id)
        summary = await self.get_session_summary(session_id)
        return messages, summary

    async def add_to_short_term_memory(self, session_id: str, message: dict):
        """
        Append a message to the Redis list for the session.
        Trims the list to the configured window size (MEMORY_WINDOW_SIZE).
        Refreshes the TTL on each write.
        """
        key = self._session_key(session_id)
        try:
            serialized = json.dumps(message, default=str)
            pipe = self.redis.pipeline()
            pipe.rpush(key, serialized)
            # Keep only the most recent window_size messages
            pipe.ltrim(key, -self.window_size, -1)
            pipe.expire(key, MEMORY_TTL_SECONDS)
            await pipe.execute()
        except Exception as exc:
            logger.error("add_to_short_term_memory_error", session_id=session_id, error=str(exc))

    # ------------------------------------------------------------------
    # Session summary (manual/legacy)
    # ------------------------------------------------------------------

    async def get_session_summary(self, session_id: str) -> Optional[str]:
        """
        Retrieve a pre-computed summary of older conversation context from Redis.
        Returns None if no summary exists.
        """
        key = self._summary_key(session_id)
        try:
            summary = await self.redis.get(key)
            if isinstance(summary, bytes):
                summary = summary.decode("utf-8")
            return summary
        except Exception as exc:
            logger.error("get_session_summary_error", session_id=session_id, error=str(exc))
            return None

    async def create_session_summary(
        self, session_id: str, messages: list[dict]
    ) -> str:
        """
        Use LLM-style compression to summarize older messages.
        Creates a condensed summary and stores it in Redis.

        For now, produces a structured text summary without calling the LLM
        (to avoid circular dependencies). In production, inject the LLM client.
        """
        if not messages:
            return ""

        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                lines.append(f"{role.capitalize()}: {content[:200]}")

        summary = "Earlier conversation summary:\n" + "\n".join(lines[:20])

        key = self._summary_key(session_id)
        try:
            await self.redis.set(key, summary, ex=MEMORY_TTL_SECONDS)
        except Exception as exc:
            logger.error("create_session_summary_error", session_id=session_id, error=str(exc))

        return summary

    # ------------------------------------------------------------------
    # Auto-summarization (LLM-powered, race-condition safe)
    # ------------------------------------------------------------------

    async def maybe_summarize(self, session_id: str, llm_client: "LLMClient") -> None:
        """Check whether the session history has exceeded SUMMARY_TRIGGER_TURNS.

        Context trimming is *always* performed regardless of whether the
        summarization lock is available.  This guarantees that the active
        context window never grows unboundedly, even under high concurrency.

        If another coroutine/process holds the summarization lock we skip only
        the expensive LLM compression step and return early — the context has
        already been trimmed to a safe size.
        """
        session_key = self._session_key(session_id)
        lock_key = self._lock_key(session_id)

        try:
            raw_messages = await self.redis.lrange(session_key, 0, -1)
            length = len(raw_messages)
            turn_count = length // 2

            if turn_count < SUMMARY_TRIGGER_TURNS:
                return

            all_messages: list[dict] = []
            for raw in raw_messages:
                try:
                    all_messages.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass

            compress_count = SUMMARY_COMPRESS_TURNS * 2
            messages_to_compress = all_messages[:compress_count]
            messages_to_keep = all_messages[compress_count:]
            retain_count = SUMMARY_RETAIN_TURNS * 2
            tail_messages = (
                messages_to_keep[-retain_count:]
                if len(messages_to_keep) >= retain_count
                else messages_to_keep
            )

            # ── ALWAYS trim the live window ─────────────────────────────────
            # This runs regardless of lock state so context cannot balloon.
            pipe = self.redis.pipeline()
            pipe.delete(session_key)
            for msg in tail_messages:
                pipe.rpush(session_key, json.dumps(msg, default=str))
            pipe.expire(session_key, MEMORY_TTL_SECONDS)
            await pipe.execute()

            logger.info(
                "context_window_trimmed",
                session_id=session_id,
                before=length,
                after=len(tail_messages),
            )

            # ── Attempt LLM summarization (requires lock) ───────────────────
            lock_acquired = await self.redis.set(
                lock_key, "1", nx=True, ex=SUMMARY_LOCK_TTL
            )

            if not lock_acquired:
                # Another worker is summarizing — trimming is already done,
                # so we can safely return without summary degradation.
                logger.info(
                    "summary_lock_contention_trimmed_safely",
                    session_id=session_id,
                )
                return

            try:
                summary_text = await self._run_llm_summarization(
                    session_id, messages_to_compress, llm_client
                )
                summary_key = self._summary_key(session_id)
                await self.redis.set(summary_key, summary_text, ex=MEMORY_TTL_SECONDS)
                logger.info(
                    "auto_summarization_complete",
                    session_id=session_id,
                    compressed=len(messages_to_compress),
                    retained=len(tail_messages),
                )
            finally:
                await self.redis.delete(lock_key)

        except Exception as exc:
            logger.error(
                "maybe_summarize_error",
                session_id=session_id,
                error=str(exc),
            )
            try:
                await self.redis.delete(lock_key)
            except Exception:
                pass



    async def _run_llm_summarization(
        self,
        session_id: str,
        messages: list[dict],
        llm_client: "LLMClient",
    ) -> str:
        """
        Call the LLM with the SUMMARIZATION_PROMPT and return the summary text.
        Falls back to a plain-text concatenation if the LLM call fails.
        """
        conversation_text = "\n".join(
            f"{m.get('role', 'unknown').upper()}: {m.get('content', '')}"
            for m in messages
            if isinstance(m.get("content"), str)
        )

        prompt_messages = [
            {"role": "system", "content": SUMMARIZATION_PROMPT},
            {
                "role": "user",
                "content": f"Conversation to summarize:\n\n{conversation_text}",
            },
        ]

        try:
            response = await llm_client.complete(
                messages=prompt_messages,
                temperature=0.2,
                max_tokens=800,
            )
            raw_content = (response.content or "").strip()

            # Strip markdown code fences if present
            if raw_content.startswith("```"):
                raw_content = re.sub(r"^```(?:json)?\n?", "", raw_content)
                raw_content = re.sub(r"\n?```$", "", raw_content)

            parsed = json.loads(raw_content)
            summary_text = parsed.get("summary", raw_content)
            entities = parsed.get("entities", {})

            # Enrich summary with entity annotations
            names = entities.get("names", [])
            refs = entities.get("references", [])
            open_intents = entities.get("open_intents", [])

            enriched_parts = [summary_text]
            if names:
                enriched_parts.append(f"[Entities: {', '.join(names)}]")
            if refs:
                enriched_parts.append(f"[References: {', '.join(refs)}]")
            if open_intents:
                enriched_parts.append(f"[Open intents: {', '.join(open_intents)}]")

            return " ".join(enriched_parts)

        except json.JSONDecodeError:
            # LLM returned plain text — use it directly
            if response and response.content:
                return response.content.strip()
            return _fallback_summary(messages)
        except Exception as exc:
            logger.error(
                "llm_summarization_failed",
                session_id=session_id,
                error=str(exc),
            )
            return _fallback_summary(messages)

    # ------------------------------------------------------------------
    # Long-term memory (LTM) — write path
    # ------------------------------------------------------------------

    async def extract_and_store_long_term_memory(
        self,
        tenant_id: str,
        customer_identifier: str,
        conversation_text: str,
        llm_client: "LLMClient",
    ) -> None:
        """
        After every conversation turn, run a lightweight LLM extraction pass
        to pull stable customer facts from the current exchange and merge them
        into `customer:ltm:{tenant_id}:{customer_identifier}`.

        Anti-poisoning guards:
        - Rejects any extraction where a value contains injection patterns
        - Skips fields that are null or empty
        - Requires the LLM to return valid JSON; falls back silently on error
        """
        if not customer_identifier:
            return

        ltm_key = self._ltm_key(tenant_id, customer_identifier)

        prompt_messages = [
            {"role": "system", "content": MEMORY_EXTRACTION_PROMPT},
            {
                "role": "user",
                "content": f"Conversation:\n\n{conversation_text}",
            },
        ]

        try:
            response = await llm_client.complete(
                messages=prompt_messages,
                temperature=0.1,
                max_tokens=400,
            )
            raw_content = (response.content or "").strip()

            # Handle explicit null response
            if raw_content.lower() in ("null", "none", ""):
                logger.debug(
                    "ltm_extraction_null",
                    tenant_id=tenant_id,
                    customer_identifier=customer_identifier,
                )
                return

            # Strip markdown code fences if present
            if raw_content.startswith("```"):
                raw_content = re.sub(r"^```(?:json)?\n?", "", raw_content)
                raw_content = re.sub(r"\n?```$", "", raw_content)

            extracted: dict = json.loads(raw_content)

        except json.JSONDecodeError:
            logger.warning(
                "ltm_extraction_json_error",
                tenant_id=tenant_id,
                customer_identifier=customer_identifier,
            )
            return
        except Exception as exc:
            logger.error(
                "ltm_extraction_llm_error",
                tenant_id=tenant_id,
                customer_identifier=customer_identifier,
                error=str(exc),
            )
            return

        # Sanitize extracted values — reject injection attempts
        clean = _sanitize_ltm_extraction(extracted)
        if not clean:
            logger.debug(
                "ltm_extraction_empty_after_sanitization",
                tenant_id=tenant_id,
                customer_identifier=customer_identifier,
            )
            return

        # Merge into existing LTM record
        try:
            existing_raw = await self.redis.get(ltm_key)
            existing: dict = {}
            if existing_raw:
                try:
                    raw_str = existing_raw if isinstance(existing_raw, str) else existing_raw.decode("utf-8")
                    existing = json.loads(raw_str)
                except Exception:
                    existing = {}

            merged = _merge_ltm(existing, clean)
            await self.redis.set(
                ltm_key, json.dumps(merged, default=str), ex=MEMORY_TTL_SECONDS
            )

            logger.info(
                "ltm_extraction_stored",
                tenant_id=tenant_id,
                customer_identifier=customer_identifier,
                fields_updated=list(clean.keys()),
            )

        except Exception as exc:
            logger.error(
                "ltm_store_error",
                tenant_id=tenant_id,
                customer_identifier=customer_identifier,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Long-term memory (LTM) — read path
    # ------------------------------------------------------------------

    async def get_long_term_customer_memory(
        self, tenant_id: str, customer_id: str
    ) -> dict:
        """
        Retrieve long-term customer preferences and history.
        Priority order:
          1. LTM key (`customer:ltm:...`) — written by extraction pipeline
          2. Legacy cache key (`customer:memory:...`) — written by update_customer_memory
          3. PostgreSQL fallback for session statistics
        """
        ltm_key = self._ltm_key(tenant_id, customer_id)
        try:
            ltm_raw = await self.redis.get(ltm_key)
            if ltm_raw:
                raw_str = ltm_raw if isinstance(ltm_raw, str) else ltm_raw.decode("utf-8")
                ltm_data = json.loads(raw_str)
                logger.debug(
                    "ltm_cache_hit",
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                )
                return ltm_data
        except Exception as exc:
            logger.warning("ltm_cache_read_error", error=str(exc))

        # Fall back to legacy customer memory cache
        cache_key = self._customer_key(tenant_id, customer_id)
        try:
            cached = await self.redis.get(cache_key)
            if cached:
                raw_str = cached if isinstance(cached, str) else cached.decode("utf-8")
                return json.loads(raw_str)
        except Exception as exc:
            logger.warning("customer_memory_cache_error", error=str(exc))

        # Fall back to database query for customer history
        try:
            from app.models.agent import Message, Session as AgentSession
            from sqlalchemy import and_

            result = await self.db.execute(
                select(AgentSession)
                .where(
                    and_(
                        AgentSession.tenant_id == tenant_id,
                        AgentSession.customer_identifier == customer_id,
                        AgentSession.status.in_(["completed", "escalated"]),
                    )
                )
                .order_by(AgentSession.started_at.desc())
                .limit(5)
            )
            sessions = result.scalars().all()

            session_ids = [s.id for s in sessions]
            total_messages = 0
            recent_intents: list[str] = []

            if session_ids:
                msg_count_result = await self.db.execute(
                    select(func.count(Message.id)).where(
                        Message.session_id.in_(session_ids)
                    )
                )
                total_messages = msg_count_result.scalar() or 0

            customer_memory = {
                "customer_id": customer_id,
                "tenant_id": tenant_id,
                "total_sessions": len(sessions),
                "total_messages": total_messages,
                "last_session_at": sessions[0].started_at.isoformat() if sessions else None,
                "preferences": {},
                "recent_intents": recent_intents,
                "channels_used": list({s.channel for s in sessions}),
                "name": None,
                "email": None,
                "phone": None,
                "facts": {},
                "open_issues": [],
                "last_intent": None,
            }

            # Cache for 1 hour under the legacy key
            try:
                await self.redis.set(
                    cache_key, json.dumps(customer_memory, default=str), ex=3600
                )
            except Exception:
                pass

            return customer_memory

        except Exception as exc:
            logger.error(
                "get_long_term_customer_memory_error",
                tenant_id=tenant_id,
                customer_id=customer_id,
                error=str(exc),
            )
            return {
                "customer_id": customer_id,
                "tenant_id": tenant_id,
                "total_sessions": 0,
                "preferences": {},
                "name": None,
                "email": None,
                "phone": None,
                "facts": {},
                "open_issues": [],
                "last_intent": None,
            }

    # ------------------------------------------------------------------
    # Legacy update method
    # ------------------------------------------------------------------

    async def update_customer_memory(
        self, tenant_id: str, customer_id: str, update: dict
    ):
        """
        Update the customer memory profile after a session ends.
        Merges the update dict into the existing profile and re-caches.
        """
        current = await self.get_long_term_customer_memory(tenant_id, customer_id)
        current.update(update)

        cache_key = self._customer_key(tenant_id, customer_id)
        try:
            await self.redis.set(
                cache_key, json.dumps(current, default=str), ex=3600
            )
        except Exception as exc:
            logger.error("update_customer_memory_error", error=str(exc))

    # ------------------------------------------------------------------
    # Session cleanup
    # ------------------------------------------------------------------

    async def clear_session(self, session_id: str):
        """
        Remove all short-term memory for a session from Redis.
        Called when a session ends or is explicitly cleared.
        """
        keys = [
            self._session_key(session_id),
            self._summary_key(session_id),
            self._lock_key(session_id),
        ]
        try:
            await self.redis.delete(*keys)
            logger.info("session_memory_cleared", session_id=session_id)
        except Exception as exc:
            logger.error("clear_session_error", session_id=session_id, error=str(exc))

    # ------------------------------------------------------------------
    # Full context convenience method
    # ------------------------------------------------------------------

    async def get_full_context(
        self, session_id: str, tenant_id: str, customer_id: Optional[str]
    ) -> dict:
        """
        Convenience method: fetch short-term memory, summary, and customer profile.
        Returns a unified context dict for the orchestrator.
        """
        short_term = await self.get_short_term_memory(session_id)
        summary = await self.get_session_summary(session_id)
        customer_memory: dict = {}

        if customer_id:
            customer_memory = await self.get_long_term_customer_memory(tenant_id, customer_id)

        return {
            "messages": short_term,
            "summary": summary,
            "customer_profile": customer_memory,
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _fallback_summary(messages: list[dict]) -> str:
    """Produce a plain-text summary when the LLM is unavailable."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str) and content:
            lines.append(f"{role.capitalize()}: {content[:200]}")
    return "Earlier conversation summary:\n" + "\n".join(lines[:20])


def _is_injection(value: str) -> bool:
    """Return True if the string contains a suspected prompt-injection payload."""
    return bool(_INJECTION_PATTERNS.search(value))


def _sanitize_ltm_extraction(extracted: dict) -> dict:
    """
    Filter LTM extraction results:
    - Remove null / empty values
    - Reject any scalar string value that matches injection patterns
    - Return clean dict; returns empty dict if nothing safe remains
    """
    clean: dict = {}

    # Scalar fields
    for field in ("name", "email", "phone", "account_type", "location", "last_intent"):
        val = extracted.get(field)
        if val and isinstance(val, str):
            if not _is_injection(val):
                clean[field] = val

    # List fields
    for field in ("preferences", "open_issues"):
        items = extracted.get(field)
        if isinstance(items, list):
            safe_items = [
                i for i in items
                if isinstance(i, str) and i and not _is_injection(i)
            ]
            if safe_items:
                clean[field] = safe_items

    # Nested facts dict
    facts = extracted.get("facts")
    if isinstance(facts, dict):
        safe_facts = {
            k: v
            for k, v in facts.items()
            if isinstance(k, str)
            and isinstance(v, str)
            and v
            and not _is_injection(k)
            and not _is_injection(v)
        }
        if safe_facts:
            clean["facts"] = safe_facts

    return clean


def _merge_ltm(existing: dict, updates: dict) -> dict:
    """
    Merge extracted LTM updates into the existing record.
    - Scalar fields: overwrite with new value
    - List fields (preferences, open_issues): union, deduplicated
    - Facts dict: merge, new values overwrite old
    """
    merged = dict(existing)

    for field in ("name", "email", "phone", "account_type", "location", "last_intent"):
        if field in updates:
            merged[field] = updates[field]

    for field in ("preferences", "open_issues"):
        if field in updates:
            old_list = merged.get(field, [])
            if not isinstance(old_list, list):
                old_list = []
            combined = list(dict.fromkeys(old_list + updates[field]))
            merged[field] = combined

    if "facts" in updates:
        existing_facts = merged.get("facts", {})
        if not isinstance(existing_facts, dict):
            existing_facts = {}
        existing_facts.update(updates["facts"])
        merged["facts"] = existing_facts

    return merged

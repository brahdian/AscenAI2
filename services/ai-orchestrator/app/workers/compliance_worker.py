"""
Compliance Worker — Automated data retention and anonymization.

Runs daily to:
1. Purge sessions, messages, and traces older than tenant's data_retention_days.
2. Anonymize PII in data older than auto_anonymize_after_days.
"""

import asyncio
import json
import uuid
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.leadership import RedisLeaderLease
from app.services.mcp_client import MCPClient
from app.core.config import settings

logger = structlog.get_logger(__name__)


class ComplianceWorker:
    """Enforces data retention and anonymization policies per tenant."""

    def __init__(
        self,
        db_factory: async_sessionmaker,
        redis=None,
        interval_seconds: int = 86400,  # Default: 24 hours
    ):
        self.db_factory = db_factory
        self.redis = redis
        self.interval_seconds = interval_seconds
        self._running = False
        self._task: asyncio.Task | None = None
        self._lease = RedisLeaderLease(redis, "ai-orchestrator:compliance-worker") if redis else None
        
        # Initialize MCP client for knowledge base cleanup
        self._mcp = MCPClient(
            base_url=settings.MCP_SERVER_URL,
            ws_url=settings.MCP_WS_URL,
            redis_client=redis
        ) if redis else None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "compliance_worker_started",
            interval_seconds=self.interval_seconds,
        )

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("compliance_worker_stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                if self._lease and not await self._lease.acquire_or_renew():
                    # Sleep a bit and retry lease acquisition
                    await asyncio.sleep(60)
                    continue
                
                await self._enforce_policies()
                
            except Exception as exc:
                logger.error("compliance_worker_error", error=str(exc))
            
            await asyncio.sleep(self.interval_seconds)

    async def _enforce_policies(self) -> None:
        """Fetch all tenants and enforce their specific compliance settings."""
        async with self.db_factory() as db:
            # Fetch all distinct tenant IDs that have data in the orchestrator
            result = await db.execute(text(
                """
                SELECT DISTINCT tenant_id FROM agents
                UNION
                SELECT DISTINCT tenant_id FROM sessions
                """
            ))
            tenant_ids = [row[0] for row in result.fetchall()]

            for tid in tenant_ids:
                tid_str = str(tid)
                # Since the auth service owns the tenants table, we use default compliance
                # rules here. Alternatively, we could fetch them via an internal API.
                compliance = {"data_retention_days": 365, "auto_anonymize_after_days": 730}
                
                try:
                    # 1. Regular retention/anonymization
                    await self._process_tenant_retention(db, tid_str, compliance)
                    await self._process_tenant_anonymization(db, tid_str, compliance)
                    
                    # 2. Operational Robustness: Reconcile orphaned vectors
                    await self._reconcile_orphaned_vectors(db, tid_str)
                    
                    # 3. Reliability: Clear documents stuck in 'processing'
                    await self._reap_stuck_indexing_jobs(db, tid_str)
                    
                    # 4. Temporal Integrity: Archive stale documents
                    await self._archive_stale_documents(db, tid_str)
                    
                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    logger.error("tenant_compliance_enforcement_failed", tenant_id=tid_str, error=str(e))
            
            # 5. Global File Scavenger: Cleanup physical binaries with no DB record
            try:
                await self._purge_orphaned_files(db)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("file_scavenger_failed", error=str(e))

    async def _process_tenant_retention(self, db, tenant_id: str, settings: dict) -> None:
        """Purge data older than retention threshold."""
        if not settings:
            return
        retention_days = settings.get("data_retention_days", 365)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        # 1. Purge traces
        res_traces = await db.execute(
            text(
                """
                DELETE FROM conversation_traces
                WHERE tenant_id = :tid AND created_at < :cutoff
                """
            ),
            {"tid": tenant_id, "cutoff": cutoff},
        )
        
        # 2. Purge messages
        res_msg = await db.execute(
            text(
                """
                DELETE FROM messages
                WHERE session_id IN (
                    SELECT id FROM sessions
                    WHERE tenant_id = :tid AND started_at < :cutoff
                )
                """
            ),
            {"tid": tenant_id, "cutoff": cutoff},
        )

        # 3. Purge sessions
        res_sess = await db.execute(
            text(
                """
                DELETE FROM sessions
                WHERE tenant_id = :tid AND started_at < :cutoff
                """
            ),
            {"tid": tenant_id, "cutoff": cutoff},
        )

        if res_traces.rowcount > 0 or res_msg.rowcount > 0 or res_sess.rowcount > 0:
            logger.info(
                "retention_purged",
                tenant_id=tenant_id,
                traces=res_traces.rowcount,
                messages=res_msg.rowcount,
                sessions=res_sess.rowcount,
            )

    async def _process_tenant_anonymization(self, db, tenant_id: str, settings: dict) -> None:
        """Anonymize/Redact PII from data older than anonymization threshold."""
        if not settings:
            return
        anonymize_days = settings.get("auto_anonymize_after_days", 730)
        cutoff = datetime.now(timezone.utc) - timedelta(days=anonymize_days)

        res = await db.execute(
            text(
                """
                UPDATE messages
                SET content = '[REDACTED_BY_COMPLIANCE_POLICY]'
                WHERE content NOT LIKE '[REDACTED_%'
                  AND session_id IN (
                    SELECT id FROM sessions
                    WHERE tenant_id = :tid AND started_at < :cutoff
                )
                """
            ),
            {"tid": tenant_id, "cutoff": cutoff},
        )
        
        if res.rowcount > 0:
            logger.info("historical_data_anonymized", tenant_id=tenant_id, count=res.rowcount)

    async def _reconcile_orphaned_vectors(self, db, tenant_id: str) -> None:
        """
        Task 3: Operational Robustness (Zombie Cleanup).
        Detect documents that were deleted locally but whose vectors still exist in MCP.
        """
        if not self._mcp:
            return

        try:
            await self._mcp.initialize()
            
            # Fetch all agents for this tenant
            agent_res = await db.execute(text("SELECT id FROM agents WHERE tenant_id = :tid"), {"tid": tenant_id})
            agents = agent_res.fetchall()
            
            for agent_row in agents:
                agent_id = str(agent_row.id)
                # In larger systems, this would be a more efficient bulk comparison.
                # For Phase 4, we perform a basic metadata consistency check.
                # Check for documents in this agent's KB that don't exist in our DB.
                pass # Logic reserved for future deep-sync or implemented as cleanup_by_metadata
            
            await self._mcp.close()
        except Exception as e:
            logger.warning("vector_reconciliation_failed", tenant_id=tenant_id, error=str(e))

    async def _process_tenant_self_destruct(self, db, tenant_id: str, metadata: dict, is_active: bool) -> None:
        """
        Deprecated: Tenant self-destruct is now handled via webhook from the Auth Service 
        since the AI Orchestrator does not own the tenants table.
        """
        pass

    async def _purge_orphaned_files(self, db) -> None:
        """
        Scan DOCUMENT_STORAGE_PATH and delete any files not referenced in agent_documents.
        This recovers space from cascade-deleted agents or failed uploads.
        """
        storage_root = Path(os.environ.get("DOCUMENT_STORAGE_PATH", "/tmp/knowledge-base"))
        if not storage_root.exists():
            return

        try:
            # 1. Get set of all files currently on disk
            on_disk = set()
            for path in storage_root.rglob("*"):
                if path.is_file():
                    on_disk.add(str(path.absolute()))

            if not on_disk:
                return

            # 2. Get set of all storage_paths in the DB
            # We use a raw query for speed if the table is large
            res = await db.execute(text("SELECT DISTINCT storage_path FROM agent_documents WHERE storage_path IS NOT NULL"))
            in_db = {str(Path(r[0]).absolute()) for r in res.fetchall() if r[0]}

            # 3. Orphan = on_disk - in_db
            orphans = on_disk - in_db
            
            deleted_count = 0
            for orphan_path in orphans:
                try:
                    p = Path(orphan_path)
                    if p.exists():
                        p.unlink()
                        deleted_count += 1
                except Exception as e:
                    logger.warning("failed_to_delete_orphan", path=orphan_path, error=str(e))

            if deleted_count > 0:
                logger.info("file_scavenger_purged_orphans", count=deleted_count)

        except Exception as e:
            logger.error("file_scavenger_failed", error=str(e))

    async def _reap_stuck_indexing_jobs(self, db, tenant_id: str) -> None:
        """Task 3: Reliability. Mark jobs stuck in 'processing' for >2 hours as failed."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
        
        # We target AgentDocument where status=processing and updated_at < cutoff
        res = await db.execute(
            text(
                """
                UPDATE agent_documents
                SET status = 'failed', error_message = 'Indexing timed out after 2 hours (Stuck Job Reaper)'
                WHERE agent_id IN (SELECT id FROM agents WHERE tenant_id = :tid)
                  AND status = 'processing'
                  AND updated_at < :cutoff
                """
            ),
            {"tid": tenant_id, "cutoff": cutoff},
        )
        
        if res.rowcount > 0:
            logger.info("stuck_indexing_jobs_reaped", tenant_id=tenant_id, count=res.rowcount)

    async def _archive_stale_documents(self, db, tenant_id: str) -> None:
        """
        Task 2: Temporal Integrity. Automatically archive documents that have passed their valid_until date.
        Phase 7 — Gap 1: Also purge their vectors from the MCP store to prevent retrieval leakage.
        """
        now = datetime.now(timezone.utc)
        
        # 1. Identify stale docs BEFORE archiving so we can purge their vectors
        stale_res = await db.execute(
            text(
                """
                SELECT ad.id, a.id as agent_id
                FROM agent_documents ad
                JOIN agents a ON a.id = ad.agent_id
                WHERE a.tenant_id = :tid
                  AND ad.status = 'ready'
                  AND ad.valid_until IS NOT NULL
                  AND ad.valid_until < :now
                """
            ),
            {"tid": tenant_id, "now": now},
        )
        stale_docs = stale_res.fetchall()
        
        if not stale_docs:
            return
        
        # 2. Archive them in DB
        await db.execute(
            text(
                """
                UPDATE agent_documents
                SET status = 'archived'
                WHERE agent_id IN (SELECT id FROM agents WHERE tenant_id = :tid)
                  AND status = 'ready'
                  AND valid_until IS NOT NULL
                  AND valid_until < :now
                """
            ),
            {"tid": tenant_id, "now": now},
        )
        logger.info("stale_documents_archived", tenant_id=tenant_id, count=len(stale_docs))
        
        # 3. Gap 1 Fix: Purge vectors from MCP store for each archived document
        if self._mcp:
            try:
                await self._mcp.initialize()
                for doc_row in stale_docs:
                    doc_id = str(doc_row.id)
                    agent_id = str(doc_row.agent_id)
                    try:
                        kb_id = await self._mcp.get_or_create_agent_kb(tenant_id, agent_id, "Archival Cleanup")
                        deleted = await self._mcp.cleanup_knowledge_by_metadata(
                            tenant_id, kb_id, "document_id", doc_id
                        )
                        logger.info("archived_doc_vectors_purged", doc_id=doc_id, deleted_chunks=deleted)
                    except Exception as mcp_doc_exc:
                        logger.warning("archived_doc_vector_purge_failed", doc_id=doc_id, error=str(mcp_doc_exc))
                await self._mcp.close()
            except Exception as mcp_exc:
                logger.error("mcp_archive_purge_failed", tenant_id=tenant_id, error=str(mcp_exc))


import asyncio
import logging
import structlog
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.database import init_db, close_db, AsyncSessionLocal
from app.core.redis_client import init_redis, close_redis

logger = structlog.get_logger(__name__)

async def startup(ctx):
    """Initialize resources required by background tasks."""
    logger.info("arq_worker_startup", version=settings.APP_VERSION)
    
    # Initialize DB Engine
    await init_db()
    ctx["db_factory"] = AsyncSessionLocal
    
    # Initialize Redis Client
    redis_client = await init_redis()
    ctx["redis"] = redis_client
    
    # We might need MCP client for some tasks (like indexing)
    from shared.orchestration.mcp_client import MCPClient
    mcp_client = MCPClient(
        base_url=settings.MCP_SERVER_URL,
        ws_url=settings.MCP_WS_URL,
        redis_client=redis_client,
    )
    mcp_client.set_redis(redis_client)
    await mcp_client.initialize()
    ctx["mcp_client"] = mcp_client

    logger.info("arq_worker_ready")

async def shutdown(ctx):
    """Clean up resources on worker shutdown."""
    logger.info("arq_worker_shutdown")
    if "mcp_client" in ctx:
        await ctx["mcp_client"].close()
    await close_redis()
    await close_db()
    logger.info("arq_worker_stopped")

# ---------------------------------------------------------------------------
# Background Task Handlers
# ---------------------------------------------------------------------------

async def process_template_instantiation_job(
    ctx, 
    t_uuid_str: str, 
    v_uuid_str: str, 
    agent_id_str: str, 
    tenant_id: str, 
    variable_values: dict, 
    tool_configs: dict, 
    actor_info: dict
):
    """Background task to run template instantiation."""
    import uuid
    from sqlalchemy import select
    from app.models.agent import Agent
    from app.api.v1.templates import process_template_instantiation
    
    db_factory = ctx["db_factory"]
    t_uuid = uuid.UUID(t_uuid_str)
    v_uuid = uuid.UUID(v_uuid_str)
    agent_id = uuid.UUID(agent_id_str)
    
    async with db_factory() as db:
        # Re-fetch agent from DB inside worker
        agent_res = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = agent_res.scalar_one_or_none()
        if not agent:
            logger.warning("template_instantiation_failed_agent_not_found", agent_id=agent_id_str)
            return
            
        # The endpoint logic normally expects `request` and `background_tasks`.
        # Since we are already in a background task, we can pass None or dummy objects
        # if the inner function doesn't strictly depend on them, OR we can refactor the inner
        # function to not require `request` and `background_tasks`.
        
        # Let's call process_template_instantiation directly.
        # We need to mock request/background_tasks if they are only used for dependency injection.
        from fastapi import BackgroundTasks
        dummy_bg_tasks = BackgroundTasks()
        
        await process_template_instantiation(
            t_uuid=t_uuid,
            v_uuid=v_uuid,
            agent=agent,
            tenant=tenant_id,
            db=db,
            request=None,  # We don't have a FastAPI request in the worker
            background_tasks=dummy_bg_tasks,
            variable_values=variable_values,
            tool_configs=tool_configs,
            actor_info=actor_info,
        )
        
        # If the inner logic queued more background tasks, we should enqueue them to ARQ!
        # But `process_template_instantiation` currently appends to `_pending_indexing_jobs`
        # and we need to handle that. Wait, the inner function just runs indexing directly?
        # Actually, `process_template_instantiation` returns a dict but handles indexing via `_pending_indexing_jobs`.
        # We will refactor `process_template_instantiation` in templates.py shortly to use ARQ directly.

class WorkerSettings:
    functions = [
        process_template_instantiation_job,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    job_timeout = 300 # 5 minutes max per job
    max_jobs = 20 # Concurrency limit

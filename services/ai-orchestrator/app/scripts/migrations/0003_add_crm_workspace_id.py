import asyncio
import structlog
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

logger = structlog.get_logger(__name__)

async def upgrade():
    """Add crm_workspace_id column to agents table."""
    logger.info("migration_start", name="0003_add_crm_workspace_id")
    
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Check if column exists first
            res = await session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='agents' AND column_name='crm_workspace_id';
            """))
            if not res.fetchone():
                await session.execute(text("ALTER TABLE agents ADD COLUMN crm_workspace_id UUID;"))
                logger.info("column_added", table="agents", column="crm_workspace_id")
            else:
                logger.info("column_exists", table="agents", column="crm_workspace_id")

    logger.info("migration_complete", name="0003_add_crm_workspace_id")

if __name__ == "__main__":
    asyncio.run(upgrade())

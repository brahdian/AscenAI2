import asyncio
import uuid
from sqlalchemy import select, text
from app.core.database import AsyncSessionLocal
from app.models.template import AgentTemplate

async def check_db():
    async with AsyncSessionLocal() as session:
        try:
            res = await session.execute(select(AgentTemplate))
            templates = res.scalars().all()
            print(f"Total Templates: {len(templates)}")
            for t in templates:
                print(f"Key: {t.key}, Name: {t.name}, Is Active: {t.is_active}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_db())

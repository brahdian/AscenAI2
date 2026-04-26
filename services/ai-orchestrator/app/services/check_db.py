
import asyncio
import json
import uuid
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def check_templates():
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT key, name FROM agent_templates"))
        rows = result.all()
        print(f"Total templates in DB: {len(rows)}")
        for row in rows:
            print(f"- {row.key}: {row.name}")

if __name__ == "__main__":
    asyncio.run(check_templates())

import asyncio

from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.tenant import Tenant


async def migrate_plans():
    async with AsyncSessionLocal() as db:
        print("--- Migrating Tenant Plans ---")
        
        mapping = {
            "text_growth": "starter",
            "voice_growth": "growth",
            "voice_business": "business",
            "professional": "growth",
        }
        
        for old, new in mapping.items():
            result = await db.execute(
                update(Tenant)
                .where(Tenant.plan == old)
                .values(plan=new)
            )
            print(f"Migrated '{old}' -> '{new}': {result.rowcount} rows")
            
        await db.commit()
        print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate_plans())

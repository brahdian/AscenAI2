import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import os
from app.guardrails.voice_agent_guardrails import generate_multilingual_greeting
from app.core.config import settings

async def main():
    engine = create_async_engine(settings.DATABASE_URL)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with AsyncSessionLocal() as db:
        text1 = await generate_multilingual_greeting(
            db, 
            primary_language="en", 
            supported_languages=["fr", "es"], 
            custom_greeting="Welcome to AscenAI"
        )
        print("TEST 1 (en, [fr, es]):", text1)
        
        text2 = await generate_multilingual_greeting(
            db, 
            primary_language="en", 
            supported_languages=["fr"], 
            custom_greeting="Welcome to AscenAI"
        )
        print("TEST 2 (en, [fr]):", text2)

if __name__ == "__main__":
    asyncio.run(main())

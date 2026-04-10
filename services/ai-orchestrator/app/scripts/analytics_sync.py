import asyncio
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func, text
from app.core.database import AsyncSessionLocal, init_db
from app.models.agent import Session as AgentSession, Message

async def sync_analytics():
    print("--- Synchronizing Analytics ---")
    await init_db()
    async with AsyncSessionLocal() as db:
        # 1. Get all Tenant IDs that have sessions
        res = await db.execute(select(AgentSession.tenant_id).distinct())
        tenant_ids = [r[0] for r in res.all()]
        
        for tid in tenant_ids:
            print(f"Processing tenant: {tid}")
            
            # Count actual sessions
            sess_res = await db.execute(select(func.count(AgentSession.id)).where(AgentSession.tenant_id == tid))
            actual_sessions = sess_res.scalar() or 0
            
            # Count actual messages
            msg_res = await db.execute(select(func.count(Message.id)).where(Message.tenant_id == tid))
            actual_messages = msg_res.scalar() or 0
            
            # Calculate Chat Units (Floor = 1 unit per session)
            # Tier: 1 unit for turns 1-10, 2 units for 11-20, etc.
            # Simplified: sum(max(1, ceil(turns/10))) per session
            chat_units = 0
            sessions_query = await db.execute(select(AgentSession.id, AgentSession.turn_count).where(AgentSession.tenant_id == tid))
            for sid, turns in sessions_query.all():
                # Floor is 1. Increment every 10 turns.
                units = 1 + (max(0, turns - 1) // 10)
                chat_units += units

            print(f"  -> Sessions: {actual_sessions}, Messages: {actual_messages}, Chat Units: {chat_units}")
            
            # Update tenant_usage table (Raw SQL to avoid cross-service model dependencies if missing)
            await db.execute(text("""
                UPDATE tenant_usage 
                SET current_month_sessions = :sessions,
                    current_month_messages = :messages,
                    current_month_chat_units = :chat_units,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tid AS UUID)
            """), {"sessions": actual_sessions, "messages": actual_messages, "chat_units": chat_units, "tid": str(tid)})
            
            # Update agent_analytics (daily rollup - simplified sync to 'today')
            today = datetime.now(timezone.utc).date()
            agent_ids_res = await db.execute(select(AgentSession.agent_id).where(AgentSession.tenant_id == tid).distinct())
            for (aid,) in agent_ids_res.all():
                # Calc per agent sessions
                a_sess_res = await db.execute(select(func.count(AgentSession.id)).where(AgentSession.agent_id == aid))
                a_sessions = a_sess_res.scalar() or 0
                
                # Calc per agent assistant messages (requires join with sessions)
                a_msg_query = text("""
                    SELECT count(m.id) 
                    FROM messages m
                    JOIN sessions s ON m.session_id = s.id
                    WHERE s.agent_id = CAST(:aid AS UUID) AND m.role = 'assistant'
                """)
                a_msg_res = await db.execute(a_msg_query, {"aid": str(aid)})
                a_messages = a_msg_res.scalar() or 0
                
                a_units = 0
                a_sessions_query = await db.execute(select(AgentSession.turn_count).where(AgentSession.agent_id == aid))
                for (turns,) in a_sessions_query.all():
                    a_units += 1 + (max(0, turns - 1) // 10)
                
                # Check if row exists for today
                check_query = text("SELECT id FROM agent_analytics WHERE agent_id = CAST(:aid AS UUID) AND date = :today")
                check_res = await db.execute(check_query, {"aid": str(aid), "today": today})
                
                if check_res.scalar_one_or_none():
                    await db.execute(text("""
                        UPDATE agent_analytics 
                        SET total_sessions = :sessions,
                            total_messages = :messages,
                            total_chat_units = :units
                        WHERE agent_id = CAST(:aid AS UUID) AND date = :today
                    """), {"sessions": a_sessions, "messages": a_messages, "units": a_units, "aid": str(aid), "today": today})
                else:
                    await db.execute(text("""
                        INSERT INTO agent_analytics (id, tenant_id, agent_id, date, total_sessions, total_messages, total_chat_units, total_tokens_used, avg_response_latency_ms, estimated_cost_usd)
                        VALUES (:id, CAST(:tid AS UUID), CAST(:aid AS UUID), :today, :sessions, :messages, :units, 0, 0, 0)
                    """), {"id": str(uuid.uuid4()), "tid": str(tid), "aid": str(aid), "today": today, "sessions": a_sessions, "messages": a_messages, "units": a_units})

        await db.commit()
        print("\nSync Complete!")

if __name__ == "__main__":
    asyncio.run(sync_analytics())

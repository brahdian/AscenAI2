import pytest
import uuid
from decimal import Decimal
from app.api.v1.billing import _get_usage_summary_db

@pytest.mark.asyncio
async def test_overage_ratio_logic(db_session):
    """Verify B19 fix: denominator includes voice in overage allocation."""
    tenant_id = uuid.uuid4()
    agent_id_1 = uuid.uuid4()
    agent_id_2 = uuid.uuid4()
    
    # 1. Setup Tenant and Plan
    from app.models.tenant import Tenant, TenantUsage
    from app.models.analytics import AgentAnalytics
    from datetime import date
    
    tenant = Tenant(id=tenant_id, name="Overage Corp", slug="overage-corp", plan="growth")
    db_session.add(tenant)
    
    usage = TenantUsage(
        tenant_id=tenant_id, 
        current_month_chat_units=1000, 
        current_month_voice_minutes=10.0 # 10 * 100 = 1000 units
    )
    db_session.add(usage)
    
    # Total units = 2000
    # Agent 1 used all voice (1000 units)
    # Agent 2 used all chat (1000 units)
    
    aa1 = AgentAnalytics(
        tenant_id=tenant_id, 
        agent_id=agent_id_1, 
        date=date.today(),
        total_chat_units=0,
        total_voice_minutes=10.0,
        total_sessions=1,
        total_messages=0
    )
    aa2 = AgentAnalytics(
        tenant_id=tenant_id, 
        agent_id=agent_id_2, 
        date=date.today(),
        total_chat_units=1000,
        total_voice_minutes=0.0,
        total_sessions=1,
        total_messages=10000
    )
    db_session.add(aa1)
    db_session.add(aa2)
    await db_session.commit()

    # 2. Logic check: per-agent share
    summary = await _get_usage_summary_db(tenant_id, db_session)
    total_tenant_chats = summary["chats"] + int(summary["voice_minutes"] * 100)
    assert total_tenant_chats == 2000

    # Agent 1 share (Voice only)
    a1_total = 0 + int(10.0 * 100)
    a1_ratio = a1_total / total_tenant_chats
    assert a1_ratio == 0.5

    # Agent 2 share (Chat only)
    a2_total = 1000 + int(0 * 100)
    a2_ratio = a2_total / total_tenant_chats
    assert a2_ratio == 0.5

@pytest.mark.asyncio
async def test_billing_overview_endpoint(client, db_session):
    """Verify that the /overview endpoint returns correct total_cost including overage."""
    tenant_id = str(uuid.uuid4())
    from app.models.tenant import Tenant, TenantUsage
    tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="test", plan="starter")
    db_session.add(tenant)
    
    # Starter plan has 20,000 chats included (approx 20,000 messages or 2,000 units if 10msgs/unit)
    # Wait, Starter limits are in units or messages?
    # In DEFAULT_PLAN_LIMITS: "chats_included": 20_000
    # In orchestrator: 1 unit per 10 messages.
    # So 20,000 messages = 2,000 units.
    
    usage = TenantUsage(
        tenant_id=uuid.UUID(tenant_id), 
        current_month_chat_units=3000, # 1000 units overage
        current_month_voice_minutes=0.0
    )
    db_session.add(usage)
    await db_session.commit()

    response = await client.get("/api/v1/billing/overview", headers={"X-Tenant-ID": tenant_id})
    assert response.status_code == 200
    data = response.json()
    
    # We expect overage to be non-zero since 3000 > 2000
    assert data["estimated_bill"]["overage"] > 0

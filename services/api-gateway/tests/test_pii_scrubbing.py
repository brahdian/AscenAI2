import pytest
import uuid
from app.models.tenant import PendingAgentPurchase
from app.core.pii import redact_pii

@pytest.mark.asyncio
async def test_pii_redaction_logic():
    """Verify that the redact_pii utility actually scrubs sensitive data."""
    sensitive_config = {
        "name": "Dr. John Doe",
        "email": "john.doe@example.com",
        "phone": "555-0199",
        "ssn": "123-45-6789",
        "instructions": "Patient Mary Smith has a heart condition. Call her at 555-1234."
    }
    
    redacted = redact_pii(sensitive_config)
    
    assert redacted["name"] != "Dr. John Doe"
    assert "Dr. John Doe" not in redacted["instructions"]
    assert "Mary Smith" not in redacted["instructions"]
    assert "555-0199" not in str(redacted)
    assert "123-45-6789" not in str(redacted)
    # Check that placeholders are injected (regex based or Presidio based)
    assert "[REDACTED" in str(redacted) or "person" in str(redacted).lower()

@pytest.mark.asyncio
async def test_pending_purchase_pii_storage(client, db_session):
    """Verify that create_agent_slot_session scrubs PII before DB save."""
    # We mock stripe since we are testing the gateway logic before Stripe call
    import stripe
    from unittest.mock import patch
    
    tenant_id = str(uuid.uuid4())
    # Create tenant first
    from app.models.tenant import Tenant
    tenant = Tenant(id=uuid.UUID(tenant_id), name="Test Tenant", slug="test-tenant", email="owner@test.com")
    db_session.add(tenant)
    await db_session.commit()

    agent_config = {
        "name": "Secret Agent",
        "instructions": "Contact person is Alice at 555-6789"
    }

    with patch("stripe.checkout.Session.create") as mock_stripe:
        mock_stripe.return_value.url = "http://stripe.com/test"
        mock_stripe.return_value.id = "cs_test_123"
        
        # We call the endpoint that triggers create_agent_slot_session
        # In billing.py: create_agent_checkout_session (or similar)
        # Actually, let's test the inner function directly or the API endpoint
        response = await client.post(
            "/api/v1/billing/checkout/agent",
            json={
                "agent_id": str(uuid.uuid4()),
                "agent_config": agent_config
            },
            headers={"X-Tenant-ID": tenant_id}
        )
        
        assert response.status_code == 200
        
        # Verify DB record is scrubbed
        from sqlalchemy import select
        result = await db_session.execute(
            select(PendingAgentPurchase).where(PendingAgentPurchase.tenant_id == uuid.UUID(tenant_id))
        )
        pending = result.scalar_one()
        
        assert "Alice" not in pending.config["instructions"]
        assert "555-6789" not in pending.config["instructions"]
        assert "[REDACTED" in pending.config["instructions"]

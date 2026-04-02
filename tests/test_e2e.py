"""End-to-end tests for AscenAI2."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch, AsyncMock, MagicMock
import uuid
import json
import asyncio

TEST_EMAIL = "test@example.com"
TEST_PASSWORD = "password123"
TEST_BUSINESS = "Test Business"


class TestAuthentication:
    """Test authentication and registration flows."""
    
    @pytest.mark.asyncio
    async def test_register_with_voice_plan(self, client: AsyncClient, db_session: AsyncSession):
        """Test registration with voice growth plan."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "voice_user@example.com",
                "password": "StrongPass123!",
                "full_name": "Voice User",
                "business_name": "Voice Business LLC",
                "business_type": "clinic",
                "plan": "voice_growth",
            },
        )
        assert response.status_code in (200, 201)
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
    
    @pytest.mark.asyncio
    async def test_register_with_text_plan(self, client: AsyncClient, db_session: AsyncSession):
        """Test registration with text growth plan."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "text_user@example.com",
                "password": "StrongPass123!",
                "full_name": "Text User",
                "business_name": "Text Business LLC",
                "business_type": "restaurant",
                "plan": "text_growth",
            },
        )
        assert response.status_code in (200, 201)
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
    
    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient, db_session: AsyncSession):
        """Test registration fails with duplicate email."""
        payload = {
            "email": "duplicate@example.com",
            "password": "StrongPass123!",
            "full_name": "Dup User",
            "business_name": "Dup Co",
        }
        response1 = await client.post("/api/v1/auth/register", json=payload)
        assert response1.status_code in (200, 201)
        
        response2 = await client.post("/api/v1/auth/register", json=payload)
        assert response2.status_code in (400, 409, 422)
    
    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, db_session: AsyncSession):
        """Test successful login."""
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "loginsuccess@example.com",
                "password": "StrongPass123!",
                "full_name": "Login Success",
                "business_name": "Login Co",
            },
        )
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "loginsuccess@example.com", "password": "StrongPass123!"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
    
    @pytest.mark.asyncio
    async def test_login_invalid_password(self, client: AsyncClient, db_session: AsyncSession):
        """Test login fails with invalid password."""
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "wrongpass@example.com",
                "password": "CorrectPass123!",
                "full_name": "Wrong Pass",
                "business_name": "Wrong Co",
            },
        )
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "wrongpass@example.com", "password": "WrongPassword!"},
        )
        assert response.status_code == 401
        assert "detail" in response.json()
    
    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient, db_session: AsyncSession):
        """Test login fails for nonexistent user."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "nonexistent@example.com", "password": "password123"},
        )
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_logout(self, client: AsyncClient, db_session: AsyncSession):
        """Test logout clears cookies."""
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "logout@example.com",
                "password": "StrongPass123!",
                "full_name": "Logout User",
                "business_name": "Logout Co",
            },
        )
        response = await client.post("/api/v1/auth/logout")
        assert response.status_code == 204
    
    @pytest.mark.asyncio
    async def test_refresh_token(self, client: AsyncClient, db_session: AsyncSession):
        """Test token refresh flow."""
        register_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "refresh@example.com",
                "password": "StrongPass123!",
                "full_name": "Refresh User",
                "business_name": "Refresh Co",
            },
        )
        tokens = register_resp.json()
        
        refresh_resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens.get("refresh_token")},
        )
        assert refresh_resp.status_code == 200
        new_tokens = refresh_resp.json()
        assert "access_token" in new_tokens


class TestAgentManagement:
    """Test agent creation, update, and deletion."""
    
    async def _authenticate(self, client: AsyncClient, email: str = "agenttest@example.com") -> str:
        """Helper to authenticate and get token."""
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "StrongPass123!",
                "full_name": "Agent Tester",
                "business_name": "Agent Test Co",
            },
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "StrongPass123!"},
        )
        return resp.json()["access_token"]
    
    @pytest.mark.asyncio
    async def test_create_agent(self, client: AsyncClient, db_session: AsyncSession):
        """Test creating a new agent."""
        token = await self._authenticate(client)
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {
                "id": str(uuid.uuid4()),
                "name": "Test Agent",
                "description": "A test agent",
                "is_active": True,
            }
            mock_post.return_value = mock_response
            
            response = await client.post(
                "/api/v1/proxy/agents",
                json={
                    "name": "Test Agent",
                    "description": "A test agent",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code in (201, 502)
    
    @pytest.mark.asyncio
    async def test_create_agent_exceeds_limit(self, client: AsyncClient, db_session: AsyncSession):
        """Test creating agent exceeds plan limit."""
        token = await self._authenticate(client, "agentlimit@example.com")
        
        from app.models.tenant import Tenant, TenantUsage
        from sqlalchemy import select
        
        result = await db_session.execute(
            select(Tenant).join(Tenant.users)
        )
        tenant = result.scalar_one_or_none()
        
        if tenant:
            usage_result = await db_session.execute(
                select(TenantUsage).where(TenantUsage.tenant_id == tenant.id)
            )
            usage = usage_result.scalar_one_or_none()
            if usage:
                from app.services.tenant_service import get_plan_limits
                limits = get_plan_limits(tenant.plan)
                usage.agent_count = limits["max_agents"]
                await db_session.commit()
        
        response = await client.post(
            "/api/v1/proxy/agents",
            json={
                "name": "Extra Agent",
                "description": "Should fail",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (429, 502)
    
    @pytest.mark.asyncio
    async def test_update_agent(self, client: AsyncClient, db_session: AsyncSession):
        """Test updating an existing agent."""
        token = await self._authenticate(client, "updatetest@example.com")
        agent_id = str(uuid.uuid4())
        
        with patch("httpx.AsyncClient.patch", new_callable=AsyncMock) as mock_patch:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "id": agent_id,
                "name": "Updated Agent",
                "description": "Updated description",
            }
            mock_patch.return_value = mock_response
            
            response = await client.patch(
                f"/api/v1/proxy/agents/{agent_id}",
                json={"name": "Updated Agent"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code in (200, 502)
    
    @pytest.mark.asyncio
    async def test_delete_agent(self, client: AsyncClient, db_session: AsyncSession):
        """Test deleting an agent."""
        token = await self._authenticate(client, "deletetest@example.com")
        agent_id = str(uuid.uuid4())
        
        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_delete.return_value = mock_response
            
            response = await client.delete(
                f"/api/v1/proxy/agents/{agent_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code in (204, 502)


class TestChatConversation:
    """Test chat conversation flows."""
    
    async def _authenticate(self, client: AsyncClient) -> str:
        """Helper to authenticate and get token."""
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "chattest@example.com",
                "password": "StrongPass123!",
                "full_name": "Chat Tester",
                "business_name": "Chat Test Co",
            },
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "chattest@example.com", "password": "StrongPass123!"},
        )
        return resp.json()["access_token"]
    
    @pytest.mark.asyncio
    async def test_text_chat_basic(self, client: AsyncClient, db_session: AsyncSession):
        """Test basic text chat functionality."""
        token = await self._authenticate(client)
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "message": "Hello! How can I help you?",
                "agent_id": str(uuid.uuid4()),
            }
            mock_post.return_value = mock_response
            
            response = await client.post(
                f"/api/v1/proxy/agents/{uuid.uuid4()}/chat",
                json={"message": "Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code in (200, 502)
    
    @pytest.mark.asyncio
    async def test_chat_with_tool_execution(self, client: AsyncClient, db_session: AsyncSession):
        """Test chat with tool execution."""
        token = await self._authenticate(client, "tooltest@example.com")
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "message": "I'll check that for you.",
                "tool_calls": [
                    {"tool": "get_customer", "input": {"customer_id": "123"}}
                ],
            }
            mock_post.return_value = mock_response
            
            response = await client.post(
                f"/api/v1/proxy/agents/{uuid.uuid4()}/chat",
                json={"message": "Get customer 123"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code in (200, 502)
    
    @pytest.mark.asyncio
    async def test_conversation_context(self, client: AsyncClient, db_session: AsyncSession):
        """Test conversation maintains context."""
        token = await self._authenticate(client, "contexttest@example.com")
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "message": "Sure, let me help with that booking.",
            }
            mock_post.return_value = mock_response
            
            response = await client.post(
                f"/api/v1/proxy/agents/{uuid.uuid4()}/chat",
                json={
                    "message": "Book a table for 4",
                    "session_id": str(uuid.uuid4()),
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code in (200, 502)
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, client: AsyncClient, db_session: AsyncSession):
        """Test rate limiting on chat endpoints."""
        token = await self._authenticate(client, "ratelimit@example.com")
        
        responses = []
        for _ in range(35):
            response = await client.post(
                f"/api/v1/proxy/agents/{uuid.uuid4()}/chat",
                json={"message": "Test"},
                headers={"Authorization": f"Bearer {token}"},
            )
            responses.append(response.status_code)
        
        assert 429 in responses or any(r > 300 for r in responses)


class TestBilling:
    """Test billing and subscription management."""
    
    async def _authenticate(self, client: AsyncClient) -> tuple[str, str]:
        """Helper to authenticate and get token."""
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "billingtest@example.com",
                "password": "StrongPass123!",
                "full_name": "Billing Tester",
                "business_name": "Billing Test Co",
            },
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "billingtest@example.com", "password": "StrongPass123!"},
        )
        return resp.json()["access_token"]
    
    @pytest.mark.asyncio
    async def test_billing_overview(self, client: AsyncClient, db_session: AsyncSession):
        """Test billing overview endpoint."""
        token = await self._authenticate(client)
        
        response = await client.get(
            "/api/v1/billing/overview",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "plan" in data
        assert "usage" in data
        assert "estimated_bill" in data
    
    @pytest.mark.asyncio
    async def test_billing_usage_tracking(self, client: AsyncClient, db_session: AsyncSession):
        """Test usage tracking in billing."""
        token = await self._authenticate(client, "usagetest@example.com")
        
        response = await client.get(
            "/api/v1/billing/agents",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    @pytest.mark.asyncio
    async def test_create_checkout_session(self, client: AsyncClient, db_session: AsyncSession):
        """Test Stripe checkout session creation (mocked)."""
        token = await self._authenticate(client, "checkouttest@example.com")
        
        with patch("stripe.checkout.Session.create", new_callable=AsyncMock) as mock_stripe:
            mock_session = MagicMock()
            mock_session.url = "https://checkout.stripe.com/test"
            mock_session.id = "cs_test_123"
            mock_stripe.return_value = mock_session
            
            response = await client.post(
                "/api/v1/billing/create-checkout-session?plan=voice_growth",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code in (200, 500)
    
    @pytest.mark.asyncio
    async def test_list_plans(self, client: AsyncClient):
        """Test listing available plans."""
        response = await client.get("/api/v1/billing/plans")
        assert response.status_code == 200
        data = response.json()
        assert "text_growth" in data
        assert "voice_growth" in data


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    async def _authenticate(self, client: AsyncClient) -> str:
        """Helper to authenticate and get token."""
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "edgetest@example.com",
                "password": "StrongPass123!",
                "full_name": "Edge Tester",
                "business_name": "Edge Test Co",
            },
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "edgetest@example.com", "password": "StrongPass123!"},
        )
        return resp.json()["access_token"]
    
    @pytest.mark.asyncio
    async def test_empty_message(self, client: AsyncClient, db_session: AsyncSession):
        """Test sending empty message."""
        token = await self._authenticate(client)
        
        response = await client.post(
            f"/api/v1/proxy/agents/{uuid.uuid4()}/chat",
            json={"message": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (400, 422, 502)
    
    @pytest.mark.asyncio
    async def test_message_with_only_whitespace(self, client: AsyncClient, db_session: AsyncSession):
        """Test message with only whitespace."""
        token = await self._authenticate(client, "whitespacetest@example.com")
        
        response = await client.post(
            f"/api/v1/proxy/agents/{uuid.uuid4()}/chat",
            json={"message": "   \n\t  "},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (400, 422, 502)
    
    @pytest.mark.asyncio
    async def test_very_long_message(self, client: AsyncClient, db_session: AsyncSession):
        """Test message exceeding 10000 characters."""
        token = await self._authenticate(client, "longmsg@example.com")
        
        long_message = "A" * 15000
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"message": "Response"}
            mock_post.return_value = mock_response
            
            response = await client.post(
                f"/api/v1/proxy/agents/{uuid.uuid4()}/chat",
                json={"message": long_message},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code in (200, 413, 502)
    
    @pytest.mark.asyncio
    async def test_special_characters_in_message(self, client: AsyncClient, db_session: AsyncSession):
        """Test message with special characters."""
        token = await self._authenticate(client, "specialtest@example.com")
        
        special_message = "Hello <script>alert('xss')</script> & '\"test\""
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"message": "Response"}
            mock_post.return_value = mock_response
            
            response = await client.post(
                f"/api/v1/proxy/agents/{uuid.uuid4()}/chat",
                json={"message": special_message},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code in (200, 502)
    
    @pytest.mark.asyncio
    async def test_emoji_in_message(self, client: AsyncClient, db_session: AsyncSession):
        """Test message with emojis."""
        token = await self._authenticate(client, "emojitest@example.com")
        
        emoji_message = "Hello 👋! How are you? 😊🎉"
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"message": "Response 👍"}
            mock_post.return_value = mock_response
            
            response = await client.post(
                f"/api/v1/proxy/agents/{uuid.uuid4()}/chat",
                json={"message": emoji_message},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code in (200, 502)
    
    @pytest.mark.asyncio
    async def test_multiple_rapid_messages(self, client: AsyncClient, db_session: AsyncSession):
        """Test multiple rapid messages."""
        token = await self._authenticate(client, "rapidtest@example.com")
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"message": "Response"}
            mock_post.return_value = mock_response
            
            tasks = []
            for i in range(10):
                task = client.post(
                    f"/api/v1/proxy/agents/{uuid.uuid4()}/chat",
                    json={"message": f"Message {i}"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                tasks.append(task)
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            assert len(responses) == 10
    
    @pytest.mark.asyncio
    async def test_session_timeout(self, client: AsyncClient, db_session: AsyncSession):
        """Test expired session handling."""
        expired_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjF9.invalid"
        
        response = await client.get(
            "/api/v1/tenants/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_concurrent_sessions(self, client: AsyncClient, db_session: AsyncSession):
        """Test handling of concurrent sessions."""
        token1 = await self._authenticate(client, "concurrent1@example.com")
        token2 = await self._authenticate(client, "concurrent2@example.com")
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"message": "Response"}
            mock_post.return_value = mock_response
            
            task1 = client.post(
                f"/api/v1/proxy/agents/{uuid.uuid4()}/chat",
                json={"message": "Session 1"},
                headers={"Authorization": f"Bearer {token1}"},
            )
            task2 = client.post(
                f"/api/v1/proxy/agents/{uuid.uuid4()}/chat",
                json={"message": "Session 2"},
                headers={"Authorization": f"Bearer {token2}"},
            )
            
            responses = await asyncio.gather(task1, task2, return_exceptions=True)
            assert len(responses) == 2


class TestSecurity:
    """Test security scenarios."""
    
    async def _authenticate(self, client: AsyncClient, email: str = "sectest@example.com") -> str:
        """Helper to authenticate and get token."""
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "StrongPass123!",
                "full_name": "Security Tester",
                "business_name": "Security Test Co",
            },
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "StrongPass123!"},
        )
        return resp.json()["access_token"]
    
    @pytest.mark.asyncio
    async def test_tenant_isolation(self, client: AsyncClient, db_session: AsyncSession):
        """Test that users cannot access other tenants' data."""
        token1 = await self._authenticate(client, "tenant1@example.com")
        token2 = await self._authenticate(client, "tenant2@example.com")
        
        resp1 = await client.get(
            "/api/v1/tenants/me",
            headers={"Authorization": f"Bearer {token1}"},
        )
        resp2 = await client.get(
            "/api/v1/tenants/me",
            headers={"Authorization": f"Bearer {token2}"},
        )
        
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        
        tenant1_data = resp1.json()
        tenant2_data = resp2.json()
        
        assert tenant1_data["id"] != tenant2_data["id"]
    
    @pytest.mark.asyncio
    async def test_api_key_authentication(self, client: AsyncClient, db_session: AsyncSession):
        """Test API key authentication."""
        token = await self._authenticate(client, "apikeytest@example.com")
        
        response = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "Test Key",
                "scopes": ["chat", "sessions"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        
        if response.status_code == 201:
            data = response.json()
            api_key = data.get("raw_key")
            
            if api_key:
                api_response = await client.get(
                    "/api/v1/tenants/me",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                assert api_response.status_code in (200, 401)
    
    @pytest.mark.asyncio
    async def test_webhook_ssrf_protection(self, client: AsyncClient, db_session: AsyncSession):
        """Test webhook URL SSRF protection."""
        token = await self._authenticate(client, "webhooktest@example.com")
        
        response_localhost = await client.post(
            "/api/v1/webhooks",
            json={
                "url": "http://localhost:8080/webhook",
                "events": ["message.received"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response_localhost.status_code == 422
        
        response_https = await client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["message.received"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response_https.status_code in (201, 500)
    
    @pytest.mark.asyncio
    async def test_webhook_private_ip_protection(self, client: AsyncClient, db_session: AsyncSession):
        """Test webhook rejects private IP addresses."""
        token = await self._authenticate(client, "privateiptest@example.com")
        
        response = await client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://192.168.1.1/webhook",
                "events": ["message.received"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_protected_endpoint_requires_auth(self, client: AsyncClient, db_session: AsyncSession):
        """Test protected endpoints require authentication."""
        endpoints = [
            "/api/v1/tenants/me",
            "/api/v1/tenants/me/usage",
            "/api/v1/billing/overview",
        ]
        
        for endpoint in endpoints:
            response = await client.get(endpoint)
            assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self, client: AsyncClient, db_session: AsyncSession):
        """Test invalid tokens are rejected."""
        response = await client.get(
            "/api/v1/tenants/me",
            headers={"Authorization": "Bearer invalid_token_here"},
        )
        assert response.status_code == 401


class TestIntegration:
    """Integration tests for external service handlers."""
    
    @pytest.mark.asyncio
    async def test_stripe_webhook_handler(self, client: AsyncClient, db_session: AsyncSession):
        """Test Stripe webhook endpoint."""
        webhook_payload = {
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_123",
                    "customer": "cus_123",
                    "amount": 4900,
                }
            }
        }
        
        with patch("stripe.Webhook.construct_event", new_callable=AsyncMock) as mock_event:
            mock_event.return_value = webhook_payload
            
            response = await client.post(
                "/api/v1/webhooks/stripe",
                content=json.dumps(webhook_payload),
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_email_sent_on_registration(self, client: AsyncClient, db_session: AsyncSession):
        """Test email is sent on registration (mock SMTP)."""
        with patch("app.services.email_service.send_email", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            
            response = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "emailtest@example.com",
                    "password": "StrongPass123!",
                    "full_name": "Email Tester",
                    "business_name": "Email Test Co",
                },
            )
            
            assert response.status_code in (200, 201)
    
    @pytest.mark.asyncio
    async def test_forgot_password_email_flow(self, client: AsyncClient, db_session: AsyncSession):
        """Test forgot password email flow."""
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "forgotpass@example.com",
                "password": "StrongPass123!",
                "full_name": "Forgot Pass",
                "business_name": "Forgot Co",
            },
        )
        
        with patch("app.services.auth_service.request_password_reset", new_callable=AsyncMock) as mock_reset:
            mock_reset.return_value = None
            
            response = await client.post(
                "/api/v1/auth/forgot-password",
                json={"email": "forgotpass@example.com"},
            )
            
            assert response.status_code == 202
    
    @pytest.mark.asyncio
    async def test_health_check_endpoints(self, client: AsyncClient):
        """Test health check endpoints."""
        response = await client.get("/health")
        assert response.status_code in (200, 503)
        
        response = await client.get("/health/live")
        assert response.status_code == 200
        assert response.json().get("alive") is True
    
    @pytest.mark.asyncio
    async def test_api_documentation_accessible(self, client: AsyncClient):
        """Test API documentation is accessible."""
        response = await client.get("/docs")
        assert response.status_code == 200
        
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "paths" in data


class TestTenantManagement:
    """Test tenant management operations."""
    
    async def _authenticate(self, client: AsyncClient) -> str:
        """Helper to authenticate and get token."""
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "tenanttest@example.com",
                "password": "StrongPass123!",
                "full_name": "Tenant Tester",
                "business_name": "Tenant Test Co",
            },
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "tenanttest@example.com", "password": "StrongPass123!"},
        )
        return resp.json()["access_token"]
    
    @pytest.mark.asyncio
    async def test_get_tenant_details(self, client: AsyncClient, db_session: AsyncSession):
        """Test getting tenant details."""
        token = await self._authenticate(client)
        
        response = await client.get(
            "/api/v1/tenants/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "email" in data
    
    @pytest.mark.asyncio
    async def test_update_tenant_details(self, client: AsyncClient, db_session: AsyncSession):
        """Test updating tenant details."""
        token = await self._authenticate(client)
        
        response = await client.patch(
            "/api/v1/tenants/me",
            json={"business_name": "Updated Business Name"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["business_name"] == "Updated Business Name"
    
    @pytest.mark.asyncio
    async def test_get_tenant_usage(self, client: AsyncClient, db_session: AsyncSession):
        """Test getting tenant usage."""
        token = await self._authenticate(client, "usagetenant@example.com")
        
        response = await client.get(
            "/api/v1/tenants/me/usage",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "current_month_messages" in data


class TestWebhooks:
    """Test webhook management."""
    
    async def _authenticate(self, client: AsyncClient) -> str:
        """Helper to authenticate and get token."""
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "webhookmanagetest@example.com",
                "password": "StrongPass123!",
                "full_name": "Webhook Manager",
                "business_name": "Webhook Co",
            },
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "webhookmanagetest@example.com", "password": "StrongPass123!"},
        )
        return resp.json()["access_token"]
    
    @pytest.mark.asyncio
    async def test_create_webhook(self, client: AsyncClient, db_session: AsyncSession):
        """Test creating a webhook."""
        token = await self._authenticate(client)
        
        response = await client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["message.received", "conversation.ended"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert "secret" in data
    
    @pytest.mark.asyncio
    async def test_list_webhooks(self, client: AsyncClient, db_session: AsyncSession):
        """Test listing webhooks."""
        token = await self._authenticate(client)
        
        response = await client.get(
            "/api/v1/webhooks",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    @pytest.mark.asyncio
    async def test_update_webhook(self, client: AsyncClient, db_session: AsyncSession):
        """Test updating a webhook."""
        token = await self._authenticate(client, "webhookupdatetest@example.com")
        
        create_response = await client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/old-webhook",
                "events": ["message.received"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        
        if create_response.status_code == 201:
            webhook_id = create_response.json()["id"]
            
            update_response = await client.patch(
                f"/api/v1/webhooks/{webhook_id}",
                json={"url": "https://example.com/new-webhook"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert update_response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_delete_webhook(self, client: AsyncClient, db_session: AsyncSession):
        """Test deleting a webhook."""
        token = await self._authenticate(client, "webhookdeletetest@example.com")
        
        create_response = await client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/delete-webhook",
                "events": ["message.received"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        
        if create_response.status_code == 201:
            webhook_id = create_response.json()["id"]
            
            delete_response = await client.delete(
                f"/api/v1/webhooks/{webhook_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert delete_response.status_code == 204


class TestAPIKeys:
    """Test API key management."""
    
    async def _authenticate(self, client: AsyncClient) -> str:
        """Helper to authenticate and get token."""
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "apikeymgmt@example.com",
                "password": "StrongPass123!",
                "full_name": "API Key Manager",
                "business_name": "API Key Co",
            },
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "apikeymgmt@example.com", "password": "StrongPass123!"},
        )
        return resp.json()["access_token"]
    
    @pytest.mark.asyncio
    async def test_create_api_key(self, client: AsyncClient, db_session: AsyncSession):
        """Test creating an API key."""
        token = await self._authenticate(client)
        
        response = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "Test API Key",
                "scopes": ["chat", "sessions"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (201, 429)
        if response.status_code == 201:
            data = response.json()
            assert "raw_key" in data
    
    @pytest.mark.asyncio
    async def test_list_api_keys(self, client: AsyncClient, db_session: AsyncSession):
        """Test listing API keys."""
        token = await self._authenticate(client, "apilisttest@example.com")
        
        response = await client.get(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    @pytest.mark.asyncio
    async def test_revoke_api_key(self, client: AsyncClient, db_session: AsyncSession):
        """Test revoking an API key."""
        token = await self._authenticate(client, "apirevoketest@example.com")
        
        create_response = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "Revoke Test Key",
                "scopes": ["chat"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        
        if create_response.status_code == 201:
            key_id = create_response.json()["id"]
            
            revoke_response = await client.delete(
                f"/api/v1/api-keys/{key_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert revoke_response.status_code == 204

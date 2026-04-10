"""Tests for the /health endpoint."""
import pytest


@pytest.mark.asyncio
async def test_health_returns_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert data["service"] == "api-gateway"


@pytest.mark.asyncio
async def test_health_has_redis_key(client):
    resp = await client.get("/health")
    data = resp.json()
    assert "redis" in data

"""Tests for authentication endpoints."""
import pytest


@pytest.mark.asyncio
async def test_register_creates_tenant(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "test@example.com",
            "password": "StrongPass123!",
            "full_name": "Test User",
            "business_name": "Test Clinic",
            "business_type": "clinic",
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email_fails(client):
    payload = {
        "email": "dup@example.com",
        "password": "StrongPass123!",
        "full_name": "Dup User",
        "business_name": "Dup Co",
    }
    resp1 = await client.post("/api/v1/auth/register", json=payload)
    assert resp1.status_code in (200, 201)

    resp2 = await client.post("/api/v1/auth/register", json=payload)
    assert resp2.status_code in (400, 409, 422)


@pytest.mark.asyncio
async def test_login_with_valid_credentials(client):
    # Register first
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "login@example.com",
            "password": "StrongPass123!",
            "full_name": "Login User",
            "business_name": "Login Co",
        },
    )
    # Then login
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "StrongPass123!"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client):
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "wrongpass@example.com",
            "password": "StrongPass123!",
            "full_name": "WP User",
            "business_name": "WP Co",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "wrongpass@example.com", "password": "WrongPassword!"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth(client):
    resp = await client.get("/api/v1/tenants/me")
    assert resp.status_code == 401

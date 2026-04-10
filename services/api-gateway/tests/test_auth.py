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
    assert data["email"] == "test@example.com"
    assert data["requires_verification"] is True
    assert data["requires_payment"] is True
    assert "access_token" not in data


@pytest.mark.asyncio
async def test_register_duplicate_email_reuses_unverified_account(client):
    payload = {
        "email": "dup@example.com",
        "password": "StrongPass123!",
        "full_name": "Dup User",
        "business_name": "Dup Co",
    }
    resp1 = await client.post("/api/v1/auth/register", json=payload)
    assert resp1.status_code in (200, 201)

    resp2 = await client.post("/api/v1/auth/register", json=payload)
    assert resp2.status_code in (200, 201)
    data2 = resp2.json()
    assert data2["email"] == "dup@example.com"
    assert data2["requires_verification"] is True
    assert data2["requires_payment"] is True


@pytest.mark.asyncio
async def test_login_requires_email_verification(client):
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "login@example.com",
            "password": "StrongPass123!",
            "full_name": "Login User",
            "business_name": "Login Co",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "StrongPass123!"},
    )
    assert resp.status_code == 403
    assert "verify" in resp.json()["detail"].lower()


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

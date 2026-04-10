"""
Role-Based Access Control (RBAC) for the API Gateway.

Usage in route handlers:

    from app.core.rbac import require_role, require_scope

    @router.delete("/{user_id}")
    async def remove_member(
        user_id: str,
        request: Request,
        _role: str = require_role("owner"),   # Only owners can remove members
        db: AsyncSession = Depends(get_db),
    ):
        ...

For API-key authenticated paths also add require_scope:

    @router.post("/chat")
    async def chat(
        body: ChatRequest,
        request: Request,
        _scope = require_scope("chat:write"),
        ...
    ):
        ...
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

# Role hierarchy — higher index means more privileged
_ROLE_LEVELS: dict[str, int] = {
    "viewer":      0,
    "developer":   1,
    "admin":       2,
    "owner":       3,
    "super_admin": 4,
}


def require_role(minimum_role: str):
    """FastAPI dependency factory — raises 403 if the caller's role is below *minimum_role*.

    Works for both JWT and API-key authenticated requests.
    The role is read from ``request.state.role`` which is stamped by AuthMiddleware.
    """
    def _check(request: Request) -> str:
        role: str = getattr(request.state, "role", "viewer") or "viewer"
        if _ROLE_LEVELS.get(role, -1) < _ROLE_LEVELS.get(minimum_role, 999):
            raise HTTPException(
                status_code=403,
                detail=f"This action requires the '{minimum_role}' role or higher. "
                       f"Your current role is '{role}'.",
            )
        return role

    return Depends(_check)


def require_scope(required_scope: str):
    """FastAPI dependency — for API-key authenticated requests, validates that the key
    carries the *required_scope*.  JWT-authenticated requests skip the scope check
    (JWT callers have full role-based access).

    The scope is read from ``request.state.api_key_scopes`` set by AuthMiddleware.
    """
    def _check(request: Request) -> None:
        auth_method: str = getattr(request.state, "auth_method", "jwt") or "jwt"
        if auth_method != "api_key":
            return  # JWT callers: role-based access is sufficient

        scopes: list[str] = getattr(request.state, "api_key_scopes", []) or []
        # "admin" scope grants full access; otherwise require exact scope match
        if "admin" not in scopes and required_scope not in scopes:
            raise HTTPException(
                status_code=403,
                detail=f"API key is missing the required scope: '{required_scope}'.",
            )

    return Depends(_check)

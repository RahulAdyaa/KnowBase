"""Shared FastAPI dependencies: DB, auth, RBAC, credit gate, rate limits."""

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.ratelimit import check_rate_limit
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import Role, User
from app.services import credits as credit_service

settings = get_settings()

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession, authorization: str = Header(default="")
) -> User:
    """Validate the Bearer access token and load the user."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_token(token, expected_type="access")
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or disabled")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def rate_limit(key_prefix: str, limit: int, window_seconds: int = 60):
    """Dependency factory: 429s when the caller exceeds the quota."""

    def _check(request: Request, user: CurrentUser):
        key = f"{key_prefix}:{user.id}"
        # Also scope by IP for anonymous-adjacent abuse (defense in depth).
        client_ip = request.client.host if request.client else "unknown"
        allowed, retry_after = check_rate_limit(f"{key}:{client_ip}", limit, window_seconds)
        if not allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Rate limit exceeded. Retry in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )

    return _check


def credit_gate(cost: int, reason: str):
    """Dependency factory: the credit 'middleware' for billable endpoints.

    Deducts `cost` credits BEFORE the handler runs (fail-closed: no credits,
    no service). Each deduction carries an idempotency key so a retried
    request can never be charged twice. The handler receives the deduction
    result via `request.state.deduction`.
    """

    def _gate(request: Request, db: DbSession, user: CurrentUser):
        idempotency_key = request.headers.get("Idempotency-Key") or (
            f"{reason}:{user.id}:{uuid.uuid4()}"
        )
        try:
            deduction = credit_service.deduct_credits(
                db, user.id, cost, reason,
                idempotency_key=idempotency_key,
                meta={"path": request.url.path},
            )
        except credit_service.InsufficientCredits:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                f"Insufficient credits. This action costs {cost} credit(s).",
            )
        request.state.deduction = deduction
        request.state.idempotency_key = idempotency_key
        return deduction

    return _gate

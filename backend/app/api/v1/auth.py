"""Authentication routes: register, login, refresh, me.

OAuth entry points (/oauth/{provider}/...) are stubbed and return 501 until
a provider is registered in `security.OAUTH_PROVIDERS`.
"""

import jwt
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import (
    OAUTH_PROVIDERS,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import Role, User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services import credits as credit_service

router = APIRouter()
log = get_logger(__name__)
settings = get_settings()


def _tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: DbSession):
    email = body.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=email, hashed_password=hash_password(body.password), role=Role.USER)
    db.add(user)
    db.flush()  # need the id for the credit account
    # Welcome bonus - idempotent per user.
    try:
        credit_service.add_credits(
            db, user.id, settings.signup_bonus_credits, "signup_bonus",
            idempotency_key=f"signup_bonus:{user.id}",
        )
    except credit_service.DuplicateTransaction:
        pass
    db.commit()
    db.refresh(user)
    log.info("user_registered", extra={"user_id": user.id})
    return _tokens(user)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: DbSession):
    user = db.scalar(select(User).where(User.email == body.email.lower().strip()))
    if user is None or not verify_password(body.password, user.hashed_password):
        # Same response for unknown email vs wrong password (no user enumeration).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    log.info("user_login", extra={"user_id": user.id})
    return _tokens(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, db: DbSession):
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    return _tokens(user)


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser):
    return user


@router.get("/oauth/{provider}/login")
def oauth_login(provider: str):
    if provider not in OAUTH_PROVIDERS:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            f"OAuth provider '{provider}' is not configured yet.",
        )
    # TODO: redirect to OAUTH_PROVIDERS[provider].get_authorization_url(state=...)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED)

"""Authentication primitives: password hashing + JWT access/refresh tokens.

OAuth structure: `OAuthProvider` is the seam where real providers
(Google, Okta, Entra ID) plug in later without touching the auth routes.
"""

from datetime import datetime, timedelta, timezone
from typing import Protocol

import bcrypt
import jwt

from app.core.config import get_settings

settings = get_settings()


# ---------------------------------------------------------------------------
# Passwords (bcrypt)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a plaintext password. Raises ValueError on empty input."""
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": _now(),
        "exp": _now() + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "iat": _now(),
        "exp": _now() + timedelta(days=settings.refresh_token_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict:
    """Decode and validate a token. Raises jwt.PyJWTError on any problem."""
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"Expected {expected_type} token")
    return payload


# ---------------------------------------------------------------------------
# OAuth-ready seam
# ---------------------------------------------------------------------------

class OAuthProvider(Protocol):
    """Implement for each IdP. Returns (email, external_id, display_name)."""

    name: str

    def get_authorization_url(self, state: str) -> str: ...
    def exchange_code(self, code: str) -> tuple[str, str, str]: ...


# Registry the auth router consults; empty until providers are configured.
OAUTH_PROVIDERS: dict[str, OAuthProvider] = {}

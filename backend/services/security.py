"""Password hashing and JWT issuance.

No secret is hardcoded. If ``JWT_SECRET`` is unset the application refuses
to issue tokens rather than falling back to a default key, because a
default signing key is the same as no authentication at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import Settings, get_settings


class AuthConfigurationError(RuntimeError):
    """Raised when authentication is asked to run without a signing key."""


class TokenError(ValueError):
    """Raised for an absent, malformed, expired or wrongly signed token."""


def hash_password(plain: str) -> str:
    if not plain:
        raise ValueError("password must not be empty")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# A precomputed, unused bcrypt hash - never a real credential for any
# account. Used only to make a login attempt against a non-existent email
# take the same time as one against a real account: verify_password() is
# deliberately slow (bcrypt), so skipping the call entirely when a user
# is not found is a measurable, real timing side-channel for account
# enumeration even though the two responses are byte-identical.
_DUMMY_HASH_FOR_CONSTANT_TIME_LOGIN = bcrypt.hashpw(
    b"not-a-real-password-used-only-for-timing", bcrypt.gensalt()
).decode("utf-8")


def _secret(settings: Settings) -> str:
    if not settings.jwt_secret:
        raise AuthConfigurationError(
            "JWT_SECRET is not set. Generate one with "
            '`python -c "import secrets; print(secrets.token_urlsafe(48))"` '
            "and put it in .env. No default signing key is provided."
        )
    return settings.jwt_secret


def create_access_token(
    subject: str, role: str, settings: Settings | None = None, **extra: Any
) -> str:
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
        **extra,
    }
    return jwt.encode(payload, _secret(settings), algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    try:
        return jwt.decode(
            token, _secret(settings), algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc

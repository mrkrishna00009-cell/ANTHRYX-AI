"""Authentication endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user, require_roles
from models.enums import Role
from models.identity import User
from schemas.auth import LoginRequest, TokenResponse, UserCreate, UserOut
from services.audit import AuditLedger
from services.rate_limit import get_login_rate_limiter
from services.security import (
    AuthConfigurationError, create_access_token, hash_password, verify_password,
    _DUMMY_HASH_FOR_CONSTANT_TIME_LOGIN,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_db)) -> TokenResponse:
    key = payload.email.lower()
    limiter = get_login_rate_limiter()

    allowed, retry_after = limiter.check(key)
    if not allowed:
        # Same generic detail as an invalid-credentials response, plus a
        # standard Retry-After header - a locked-out key is throttled,
        # never told whether the account exists.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )

    user = session.execute(
        select(User).where(User.email == key)
    ).scalar_one_or_none()

    # Always run the (deliberately slow) bcrypt check, even for an unknown
    # email, against a fixed dummy hash - otherwise a nonexistent-account
    # request returns near-instantly while a real one takes the bcrypt
    # cost, letting an attacker enumerate accounts by response time alone
    # despite the two responses being otherwise identical.
    password_ok = verify_password(
        payload.password, user.password_hash if user else _DUMMY_HASH_FOR_CONSTANT_TIME_LOGIN
    )
    # Same response whether the account is unknown or the password is wrong,
    # so the endpoint cannot be used to enumerate valid accounts.
    if user is None or not password_ok:
        limiter.record_failure(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    limiter.record_success(key)
    settings = get_settings()
    try:
        token = create_access_token(str(user.id), user.role.value, settings)
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    user.last_login_at = datetime.now(timezone.utc)
    AuditLedger(session).append(
        action="USER_LOGIN", entity_type="user", entity_id=str(user.id),
        actor_id=str(user.id), payload={"role": user.role.value},
    )
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.jwt_expire_minutes,
        role=user.role,
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(
    session: Session = Depends(get_db), actor: User = Depends(require_roles(Role.ADMIN))
) -> list[User]:
    """Minimal user administration for the Settings page - list only, no
    edit/deactivate here. ADMIN-only, matching create_user's own scoping."""
    return list(session.execute(select(User).order_by(User.email)).scalars())


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    session: Session = Depends(get_db),
    actor: User = Depends(require_roles(Role.ADMIN)),
) -> User:
    existing = session.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        mine_id=payload.mine_id,
        subsidiary_id=payload.subsidiary_id,
    )
    session.add(user)
    session.flush()
    AuditLedger(session).append(
        action="USER_CREATED", entity_type="user", entity_id=str(user.id),
        actor_id=str(actor.id), payload={"role": user.role.value},
    )
    return user

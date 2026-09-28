"""Shared FastAPI dependencies: database session, current user, RBAC.

Authorization lives here and only here. The Streamlit dashboard and the
field PWA are both HTTP clients of this API and are both subject to these
checks; neither can bypass them by hiding a control in its own interface.
"""

from __future__ import annotations

import uuid
from typing import Callable, Iterable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from models.enums import Role
from models.identity import User
from models.organisation import Mine
from services import rbac
from services.audit import AuditLedger
from services.security import AuthConfigurationError, TokenError, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise CREDENTIALS_ERROR
    try:
        payload = decode_access_token(credentials.credentials)
    except AuthConfigurationError as exc:
        # Misconfiguration is a server fault, not a bad credential.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    subject = payload.get("sub")
    if not subject:
        raise CREDENTIALS_ERROR
    try:
        user = session.get(User, uuid.UUID(subject))
    except (ValueError, TypeError):
        raise CREDENTIALS_ERROR
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive or unknown"
        )
    return user


def require_roles(*allowed: Role) -> Callable[..., User]:
    allowed_set = frozenset(allowed)

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role {user.role.value} may not perform this action; "
                    f"allowed: {sorted(r.value for r in allowed_set)}"
                ),
            )
        return user

    return dependency


def require_any(allowed: Iterable[Role]) -> Callable[..., User]:
    return require_roles(*allowed)


def assert_mine_access(session: Session, user: User, mine_id) -> Mine:
    """Load a mine and confirm the caller is scoped to see it."""
    mine = session.get(Mine, mine_id)
    if mine is None:
        raise HTTPException(status_code=404, detail="Mine not found")
    if not rbac.can_access_mine(
        user.role, user.mine_id, user.subsidiary_id, mine.id, mine.subsidiary_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This mine is outside your assigned scope",
        )
    return mine


def get_ledger(session: Session = Depends(get_db)) -> AuditLedger:
    return AuditLedger(session)

"""Health and readiness endpoints.

These report the true state of the process, including whether the database
is the PostgreSQL primary or the SQLite development fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.config import get_settings
from app.database import get_engine, get_resolution
from schemas.health import DatabaseHealth, HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])

PHASE = "final-prototype"


def _database_health() -> DatabaseHealth:
    resolution = get_resolution()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        reachable = True
        detail = resolution.reason
    except (SQLAlchemyError, OSError) as exc:
        reachable = False
        detail = f"{type(exc).__name__}: {exc}"[:300]
    return DatabaseHealth(
        backend=resolution.backend,
        reachable=reachable,
        is_development_fallback=resolution.is_development_fallback,
        detail=detail,
    )


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health() -> HealthResponse:
    settings = get_settings()
    db = _database_health()
    return HealthResponse(
        status="ok" if db.reachable else "degraded",
        app=settings.app_name,
        version=__version__,
        environment=settings.environment,
        phase=PHASE,
        server_time_utc=datetime.now(timezone.utc),
        database=db,
    )


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe")
def ready() -> ReadinessResponse:
    db = _database_health()
    checks = {
        "database": "ok" if db.reachable else f"unreachable: {db.detail}",
        "database_backend": db.backend,
    }
    return ReadinessResponse(ready=db.reachable, checks=checks)

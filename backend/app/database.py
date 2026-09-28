"""Database engine and session management.

Resolution order:

1. DATABASE_URL from the environment (expected to be PostgreSQL).
2. If that URL cannot be reached and ALLOW_SQLITE_FALLBACK is true,
   fall back to a local SQLite file for development only.

The resolution result is reported honestly through /health so the running
system never implies it is on PostgreSQL when it is not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatabaseResolution:
    url: str
    backend: str                 # "postgresql" | "sqlite"
    is_development_fallback: bool
    reason: str


def _probe(url: str, timeout: int) -> tuple[bool, str]:
    """Try one connection. Returns (ok, message). Never raises."""
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        kwargs["connect_args"] = {"connect_timeout": timeout}
    try:
        engine = create_engine(url, **kwargs)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True, "connected"
    except (SQLAlchemyError, OSError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}"[:300]
    except ModuleNotFoundError as exc:          # driver not installed
        return False, f"driver missing: {exc}"


def resolve_database(settings: Settings | None = None) -> DatabaseResolution:
    settings = settings or get_settings()

    if settings.database_url:
        ok, message = _probe(settings.database_url, settings.db_connect_timeout_seconds)
        if ok:
            backend = settings.database_url.split(":", 1)[0].split("+", 1)[0]
            return DatabaseResolution(
                url=settings.database_url,
                backend=backend,
                is_development_fallback=False,
                reason="DATABASE_URL reachable",
            )
        logger.warning("DATABASE_URL unreachable (%s)", message)
        if not settings.allow_sqlite_fallback:
            raise RuntimeError(
                f"DATABASE_URL unreachable and SQLite fallback disabled: {message}"
            )
        reason = f"DATABASE_URL unreachable ({message}); using development SQLite fallback"
    else:
        if not settings.allow_sqlite_fallback:
            raise RuntimeError("DATABASE_URL is not set and SQLite fallback is disabled")
        reason = "DATABASE_URL not set; using development SQLite fallback"

    return DatabaseResolution(
        url=settings.sqlite_url,
        backend="sqlite",
        is_development_fallback=True,
        reason=reason,
    )


def make_engine(resolution: DatabaseResolution) -> Engine:
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if resolution.backend == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(resolution.url, **kwargs)


_resolution: DatabaseResolution | None = None
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_resolution() -> DatabaseResolution:
    global _resolution
    if _resolution is None:
        _resolution = resolve_database()
    return _resolution


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_resolution())
    return _engine


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autocommit=False, autoflush=False, class_=Session
        )
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_state() -> None:
    """Drop cached engine/session state. Used by tests."""
    global _resolution, _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _resolution = None
    _engine = None
    _SessionLocal = None

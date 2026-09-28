"""Database resolution: PostgreSQL primary, SQLite development fallback."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app import database
from app.config import Settings


def test_falls_back_to_sqlite_when_database_url_absent(tmp_path):
    settings = Settings(
        database_url=None,
        allow_sqlite_fallback=True,
        sqlite_fallback_path=str(tmp_path / "a.db"),
    )
    resolution = database.resolve_database(settings)
    assert resolution.backend == "sqlite"
    assert resolution.is_development_fallback is True
    assert "not set" in resolution.reason


def test_falls_back_when_postgres_unreachable(tmp_path):
    settings = Settings(
        database_url="postgresql://nobody@127.0.0.1:1/absent",
        allow_sqlite_fallback=True,
        sqlite_fallback_path=str(tmp_path / "b.db"),
        db_connect_timeout_seconds=1,
    )
    resolution = database.resolve_database(settings)
    assert resolution.backend == "sqlite"
    assert resolution.is_development_fallback is True
    assert "unreachable" in resolution.reason


def test_raises_when_fallback_disabled_and_no_url():
    settings = Settings(database_url=None, allow_sqlite_fallback=False)
    with pytest.raises(RuntimeError):
        database.resolve_database(settings)


def test_engine_executes_a_statement(tmp_path):
    settings = Settings(
        database_url=None,
        allow_sqlite_fallback=True,
        sqlite_fallback_path=str(tmp_path / "c.db"),
    )
    resolution = database.resolve_database(settings)
    engine = database.make_engine(resolution)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
    engine.dispose()


def test_session_dependency_yields_and_closes():
    gen = database.get_db()
    session = next(gen)
    assert session.execute(text("SELECT 1")).scalar() == 1
    with pytest.raises(StopIteration):
        next(gen)

"""Test fixtures.

The suite runs entirely offline: no PostgreSQL server, no Bhashini API and
no MSHA download is required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    """Force every test onto a throwaway SQLite file."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ALLOW_SQLITE_FALLBACK", "true")
    monkeypatch.setenv("SQLITE_FALLBACK_PATH", str(tmp_path / "test.db"))

    from app import config, database

    config.get_settings.cache_clear()
    database.reset_state()
    yield
    database.reset_state()
    config.get_settings.cache_clear()

    # The login rate limiter is a module-global singleton, same category
    # of per-process state as the DB engine cache above - reset it too so
    # one test's failed-login attempts can never carry over into another
    # test's rate-limit expectations regardless of run order.
    from services import rate_limit
    if rate_limit._default_limiter is not None:
        rate_limit._default_limiter.reset_all()
    rate_limit._default_limiter = None


@pytest.fixture
def db_session(_isolated_settings):
    """A session against a fresh schema built from the models."""
    from app import database
    import models

    engine = database.get_engine()
    models.Base.metadata.create_all(engine)
    session = database.get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(_isolated_settings, monkeypatch):
    from fastapi.testclient import TestClient
    from app import config, database
    import models

    # A real signing key, generated per test run. Never a fixed default.
    monkeypatch.setenv("JWT_SECRET", "test-only-" + os.urandom(16).hex())
    config.get_settings.cache_clear()
    database.reset_state()
    models.Base.metadata.create_all(database.get_engine())

    with TestClient(create_app_lazy()) as c:
        yield c


def create_app_lazy():
    from app.main import create_app
    return create_app()


@pytest.fixture
def seeded(client):
    """One admin, one subsidiary, one mine, one inspector.

    Built through the ORM rather than the API so tests do not depend on
    endpoints they are not exercising.
    """
    from app import database
    from models.enums import MineType, Role
    from models.identity import User
    from models.organisation import Mine, Subsidiary
    from services.security import hash_password

    session = database.get_sessionmaker()()
    sub = Subsidiary(code="BCCL", name="Test Subsidiary", state="Jharkhand")
    session.add(sub)
    session.flush()
    mine = Mine(
        code="TEST-01", name="Test Colliery", mine_type=MineType.UNDERGROUND,
        subsidiary_id=sub.id, state="Jharkhand",
    )
    session.add(mine)
    session.flush()
    admin = User(
        email="admin@example.com", full_name="Admin",
        password_hash=hash_password("admin-password-123"), role=Role.ADMIN,
    )
    inspector = User(
        email="inspector@example.com", full_name="Inspector",
        password_hash=hash_password("inspector-password-123"),
        role=Role.FIELD_INSPECTOR, mine_id=mine.id, subsidiary_id=sub.id,
    )
    manager = User(
        email="manager@example.com", full_name="Manager",
        password_hash=hash_password("manager-password-123"),
        role=Role.MINE_MANAGER, mine_id=mine.id, subsidiary_id=sub.id,
    )
    session.add_all([admin, inspector, manager])
    session.commit()
    data = {
        "mine_id": str(mine.id), "subsidiary_id": str(sub.id),
        "admin": admin.email, "inspector": inspector.email,
        "manager": manager.email,
    }
    session.close()
    return data


def _login(client, email, password):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin_headers(client, seeded):
    return _login(client, seeded["admin"], "admin-password-123")


@pytest.fixture
def inspector_headers(client, seeded):
    return _login(client, seeded["inspector"], "inspector-password-123")


@pytest.fixture
def manager_headers(client, seeded):
    return _login(client, seeded["manager"], "manager-password-123")

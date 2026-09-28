"""Password hashing, JWT handling and role rules."""

from __future__ import annotations

import pytest

from models.enums import Role
from services import rbac, security


def test_password_round_trip():
    hashed = security.hash_password("a-real-password")
    assert hashed != "a-real-password"
    assert security.verify_password("a-real-password", hashed)
    assert not security.verify_password("wrong", hashed)


def test_empty_password_rejected():
    with pytest.raises(ValueError):
        security.hash_password("")
    assert security.verify_password("", "whatever") is False


def test_no_token_without_a_signing_key(monkeypatch):
    """A default signing key would be the same as no authentication."""
    from app import config

    monkeypatch.delenv("JWT_SECRET", raising=False)
    config.get_settings.cache_clear()
    with pytest.raises(security.AuthConfigurationError):
        security.create_access_token("user", "ADMIN")


def test_token_round_trip(monkeypatch):
    from app import config

    monkeypatch.setenv("JWT_SECRET", "unit-test-secret-value")
    config.get_settings.cache_clear()
    token = security.create_access_token("user-1", Role.ADMIN.value)
    payload = security.decode_access_token(token)
    assert payload["sub"] == "user-1"
    assert payload["role"] == "ADMIN"


def test_tampered_token_rejected(monkeypatch):
    from app import config

    monkeypatch.setenv("JWT_SECRET", "unit-test-secret-value")
    config.get_settings.cache_clear()
    token = security.create_access_token("user-1", "ADMIN")
    with pytest.raises(security.TokenError):
        security.decode_access_token(token[:-2] + "xx")


def test_expired_token_rejected(monkeypatch):
    from app import config

    monkeypatch.setenv("JWT_SECRET", "unit-test-secret-value")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "-1")
    config.get_settings.cache_clear()
    token = security.create_access_token("user-1", "ADMIN")
    with pytest.raises(security.TokenError):
        security.decode_access_token(token)


def test_inspector_cannot_verify():
    """The person who raises a finding does not sign off its closure."""
    assert not rbac.has_role(Role.FIELD_INSPECTOR, rbac.VERIFIERS)
    assert rbac.has_role(Role.MINE_MANAGER, rbac.VERIFIERS)


def test_national_roles_see_every_mine():
    for role in (Role.ADMIN, Role.DGMS_REGULATOR):
        assert rbac.can_access_mine(role, None, None, "mine-1", "sub-1")


def test_mine_role_confined_to_its_own_mine():
    assert rbac.can_access_mine(Role.MINE_MANAGER, "mine-1", "sub-1", "mine-1", "sub-1")
    assert not rbac.can_access_mine(
        Role.MINE_MANAGER, "mine-1", "sub-1", "mine-2", "sub-1"
    )


def test_subsidiary_head_confined_to_its_subsidiary():
    assert rbac.can_access_mine(Role.SUBSIDIARY_HEAD, None, "sub-1", "mine-9", "sub-1")
    assert not rbac.can_access_mine(
        Role.SUBSIDIARY_HEAD, None, "sub-1", "mine-9", "sub-2"
    )


def test_unknown_role_string_denied():
    assert not rbac.can_access_mine("NOT_A_ROLE", "m", "s", "m", "s")
    assert not rbac.has_role("NOT_A_ROLE", rbac.VERIFIERS)

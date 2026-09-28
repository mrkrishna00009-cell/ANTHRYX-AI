"""The health endpoint must report the real backend, including the fallback."""

from __future__ import annotations


def test_health_returns_ok(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "ANTHRYX AI"
    assert body["phase"] == "final-prototype"


def test_health_declares_sqlite_fallback_honestly(client):
    body = client.get("/api/v1/health").json()
    assert body["database"]["backend"] == "sqlite"
    assert body["database"]["is_development_fallback"] is True
    assert body["database"]["reachable"] is True


def test_unprefixed_health_alias_works(client):
    assert client.get("/health").status_code == 200


def test_readiness(client):
    body = client.get("/api/v1/ready").json()
    assert body["ready"] is True
    assert body["checks"]["database"] == "ok"


def test_root_lists_entry_points(client):
    body = client.get("/").json()
    assert body["health"] == "/api/v1/health"


def test_openapi_schema_builds(client):
    assert client.get("/openapi.json").status_code == 200

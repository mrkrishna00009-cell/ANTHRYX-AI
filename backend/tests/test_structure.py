"""Guards that Phase 1 stays Phase 1."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_required_top_level_files_exist():
    for name in [
        "requirements.txt",
        ".env.example",
        ".gitignore",
        "docker-compose.yml",
        "Dockerfile",
        "README.md",
        "alembic.ini",
    ]:
        assert (REPO / name).is_file(), f"missing {name}"


def test_required_directories_exist():
    for name in [
        "backend/app",
        "backend/api/v1",
        "backend/models",
        "backend/schemas",
        "backend/services",
        "backend/integrations",
        "backend/ml",
        "backend/tests",
        "dashboard/streamlit",
        "field_app/react_pwa",
        "data/raw",
        "data/processed",
        "data/seed",
        "artifacts",
        "reports",
        "scripts",
        "docs",
    ]:
        assert (REPO / name).is_dir(), f"missing {name}"


def test_no_real_secrets_in_env_example():
    text = (REPO / ".env.example").read_text()
    assert "JWT_SECRET=" in text
    assert "BHASHINI_API_KEY=" in text
    for line in text.splitlines():
        if line.startswith(("JWT_SECRET=", "BHASHINI_API_KEY=", "BHASHINI_USER_ID=")):
            assert line.split("=", 1)[1].strip() == "", f"{line} must ship empty"


def test_no_msha_data_is_bundled():
    """Phase 1 must not invent or ship MSHA data."""
    raw = REPO / "data" / "raw"
    payload = [p for p in raw.rglob("*") if p.is_file() and p.name != ".gitkeep"]
    assert payload == [], f"unexpected data files: {payload}"


def test_migrations_exist():
    versions = REPO / "backend" / "migrations" / "versions"
    assert versions.is_dir()
    revisions = [p for p in versions.glob("*.py") if not p.name.startswith("__")]
    assert revisions, "an initial migration must exist"


def test_alembic_ini_carries_no_credential():
    text = (REPO / "alembic.ini").read_text()
    for line in text.splitlines():
        if line.strip().startswith("sqlalchemy.url"):
            assert line.split("=", 1)[1].strip() == "", (
                "alembic.ini must not embed a connection string"
            )


def test_dashboard_never_touches_the_database_directly():
    """Locked decision F4: Streamlit is an HTTP client of FastAPI."""
    import re

    pattern = re.compile(r"^\s*(import|from)\s+(sqlalchemy|models|psycopg2)\b", re.M)
    for path in (REPO / "dashboard").rglob("*.py"):
        assert not pattern.search(path.read_text()), f"{path} accesses the DB directly"


def test_field_app_is_scoped_to_field_evidence():
    """Locked decision: the React PWA is M2 only, not a second dashboard."""
    src = REPO / "field_app" / "react_pwa" / "src"
    body = " ".join(p.read_text().lower() for p in src.rglob("*.js*"))
    for forbidden in ("statutory_rules", "capa_items", "audit_log", "/risk/"):
        assert forbidden not in body, f"field app reaches beyond M2: {forbidden}"


def test_model_artifacts_are_gitignored_not_committed():
    """Phase 4: real trained artifacts now exist on disk (required for the
    app to function) - the protective intent is that they are never
    version-controlled, which .gitignore already guarantees regardless of
    what a given runtime environment happens to have on disk."""
    gitignore = (REPO / ".gitignore").read_text()
    assert "artifacts/**" in gitignore
    assert "!artifacts/.gitkeep" in gitignore


def test_forbidden_claims_absent_from_source():
    """The ledger is tamper-evident. It is not immutable and not a blockchain."""
    import re

    bad = re.compile(r"\b(immutable|blockchain)\b", re.I)
    sources = [
        p for p in (REPO / "backend").rglob("*.py")
        if "tests" not in p.parts and "migrations" not in p.parts
    ] + list((REPO / "dashboard").rglob("*.py"))
    for path in sources:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if bad.search(line):
                # Permitted only where the claim is being denied.
                assert re.search(r"not\s+(a\s+)?(immutable|blockchain)|never\b|is_immutable|is_blockchain|\"immutable\"", line, re.I), (
                    f"{path}:{number} uses a forbidden claim: {line.strip()}"
                )

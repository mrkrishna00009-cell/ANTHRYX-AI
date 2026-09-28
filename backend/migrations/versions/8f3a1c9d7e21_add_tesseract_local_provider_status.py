"""Phase 4 Part 1: add ProviderStatus.TESSERACT_LOCAL.

Tesseract is a local engine, not Bhashini. Reusing LIVE_BHASHINI to mean
"Tesseract succeeded" would misrepresent which engine actually produced
an OCR result, so a fourth, honest value is added instead. This ALTERs
the existing VARCHAR+CHECK constraint (the project uses native_enum=False
throughout precisely so this kind of change is a plain constraint update,
portable to both PostgreSQL and the SQLite dev fallback, rather than a
PostgreSQL-specific ALTER TYPE).

Does not touch any other constraint, table, or migration history.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "8f3a1c9d7e21"
down_revision = "c202af4059bb"
branch_labels = None
depends_on = None

OLD_VALUES = ("LIVE_BHASHINI", "BHASHINI_UNAVAILABLE", "DEMO_FALLBACK")
NEW_VALUES = ("LIVE_BHASHINI", "BHASHINI_UNAVAILABLE", "DEMO_FALLBACK", "TESSERACT_LOCAL")

OLD_ENUM = sa.Enum(*OLD_VALUES, name="providerstatus", native_enum=False, length=48)
NEW_ENUM = sa.Enum(*NEW_VALUES, name="providerstatus", native_enum=False, length=48)

TABLE = "incident_reports"
COLUMNS = ("asr_provider_status", "nmt_provider_status")


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    for col in COLUMNS:
        if is_sqlite:
            # SQLite has no ALTER-constraint statement; the CHECK is
            # re-derived automatically from the Python enum wherever the
            # schema is (re)built via create_all(), and this migration's
            # job on SQLite is documentation of intent, not DDL - no
            # existing row's value changes and nothing is dropped.
            continue
        with op.batch_alter_table(TABLE) as batch_op:
            batch_op.alter_column(
                col, existing_type=OLD_ENUM, type_=NEW_ENUM,
                existing_nullable=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    # Any row already carrying 'TESSERACT_LOCAL' would violate the
    # narrower constraint; that is the correct, honest failure mode for a
    # downgrade rather than silently rewriting real OCR provenance data.
    for col in COLUMNS:
        with op.batch_alter_table(TABLE) as batch_op:
            batch_op.alter_column(
                col, existing_type=NEW_ENUM, type_=OLD_ENUM,
                existing_nullable=True,
            )

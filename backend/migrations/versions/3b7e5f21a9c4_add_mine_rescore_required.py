"""Phase 5 Part 3: add mines.rescore_required.

Set True when a CAPA for a mine closes (the closure never fabricates an
immediate risk improvement - it only flags the mine's feature row as
possibly stale); cleared when the feature builder actually runs for that
mine. Purely additive: one nullable-safe boolean column with a server
default, no data migration needed for existing rows.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "3b7e5f21a9c4"
down_revision = "8f3a1c9d7e21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("mines") as batch_op:
        batch_op.add_column(
            sa.Column("rescore_required", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("mines") as batch_op:
        batch_op.drop_column("rescore_required")

"""Functional completeness audit: add ml_predictions.feature_id.

Closes a real traceability gap identified twice during release audits:
a prediction previously had no durable link back to the exact MlFeature
row it was scored from (only implicit, via mine_id/timing proximity).
Nullable and additive - historical rows are never backfilled with a
guessed value; NULL honestly means "not recorded".
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "7a2e9c05b1f3"
down_revision = "9c1d4e8a2f36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ml_predictions") as batch_op:
        batch_op.add_column(sa.Column("feature_id", sa.Uuid(), nullable=True))
        batch_op.create_index("ix_ml_predictions_feature_id", ["feature_id"])
        batch_op.create_foreign_key(
            "fk_ml_predictions_feature_id_ml_features", "ml_features",
            ["feature_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("ml_predictions") as batch_op:
        batch_op.drop_constraint("fk_ml_predictions_feature_id_ml_features", type_="foreignkey")
        batch_op.drop_index("ix_ml_predictions_feature_id")
        batch_op.drop_column("feature_id")

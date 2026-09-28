"""Product completion: add grievances, grievance_events, approval_chains,
approval_steps.

Additive only. Supersedes locked decision F6's exclusion of a
grievances table - a later explicit product instruction asked for a
real Grievance module with persistence, SLA tracking, and escalation;
this migration and models/__init__.py's docstring both record that
supersession rather than silently applying it.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "9c1d4e8a2f36"
down_revision = "3b7e5f21a9c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "grievances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mine_id", sa.Uuid(), nullable=False),
        sa.Column(
            "category",
            sa.Enum("SAFETY_CONCERN", "WAGE_DISPUTE", "LAND_ENVIRONMENTAL", "HARASSMENT", "OTHER",
                    name="grievancecategory", native_enum=False, length=48),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False),
        sa.Column("filed_by", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("OPEN", "IN_PROGRESS", "ESCALATED", "RESOLVED",
                    name="grievancestatus", native_enum=False, length=48),
            nullable=False,
        ),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("escalation_level", sa.Integer(), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["mine_id"], ["mines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["filed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_grievances_mine_id", "grievances", ["mine_id"])
    op.create_index("ix_grievances_category", "grievances", ["category"])
    op.create_index("ix_grievances_status", "grievances", ["status"])

    op.create_table(
        "grievance_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("grievance_id", sa.Uuid(), nullable=False),
        sa.Column(
            "from_status",
            sa.Enum("OPEN", "IN_PROGRESS", "ESCALATED", "RESOLVED",
                    name="grievancestatus", native_enum=False, length=48),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            sa.Enum("OPEN", "IN_PROGRESS", "ESCALATED", "RESOLVED",
                    name="grievancestatus", native_enum=False, length=48),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["grievance_id"], ["grievances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_grievance_events_grievance_id", "grievance_events", ["grievance_id"])

    op.create_table(
        "approval_chains",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capa_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "final_decision",
            sa.Enum("PENDING", "APPROVED", "REJECTED", name="approvaldecision", native_enum=False, length=48),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["capa_id"], ["capa_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capa_id", name="uq_approval_chains_capa_id"),
    )
    op.create_index("ix_approval_chains_capa_id", "approval_chains", ["capa_id"])
    op.create_index("ix_approval_chains_final_decision", "approval_chains", ["final_decision"])

    op.create_table(
        "approval_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "stage",
            sa.Enum("MINE_MANAGER", "SUBSIDIARY_GM", "CORPORATE_OFFICE",
                    name="approvalstage", native_enum=False, length=48),
            nullable=False,
        ),
        sa.Column(
            "decision",
            sa.Enum("PENDING", "APPROVED", "REJECTED", name="approvaldecision", native_enum=False, length=48),
            nullable=False,
        ),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["chain_id"], ["approval_chains.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chain_id", "stage", name="uq_approval_step_chain_stage"),
    )
    op.create_index("ix_approval_steps_chain_id", "approval_steps", ["chain_id"])


def downgrade() -> None:
    op.drop_table("approval_steps")
    op.drop_table("approval_chains")
    op.drop_table("grievance_events")
    op.drop_table("grievances")

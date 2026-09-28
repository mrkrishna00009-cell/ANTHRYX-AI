"""M4 extension - a three-stage approval chain for a CAPA/remediation
that requires sign-off above the mine level.

One ApprovalChain per CAPA that needs it (not every CAPA does - a chain
is created explicitly, not implied); three ApprovalStep rows created
with it (MINE_MANAGER, SUBSIDIARY_GM, CORPORATE_OFFICE, in that fixed
order). A stage only becomes decidable once every stage before it has
been APPROVED; a REJECTED decision at any stage ends the chain there -
it does not silently continue to the next stage.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, UuidPkMixin, enum_column
from models.enums import ApprovalDecision, ApprovalStage

STAGE_ORDER = [ApprovalStage.MINE_MANAGER, ApprovalStage.SUBSIDIARY_GM, ApprovalStage.CORPORATE_OFFICE]


class ApprovalChain(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "approval_chains"

    capa_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("capa_items.id", ondelete="CASCADE"), nullable=False, index=True, unique=True
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    final_decision: Mapped[ApprovalDecision] = enum_column(
        ApprovalDecision, nullable=False, default=ApprovalDecision.PENDING, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    steps = relationship("ApprovalStep", back_populates="chain", order_by="ApprovalStep.sequence")


class ApprovalStep(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "approval_steps"
    __table_args__ = (UniqueConstraint("chain_id", "stage", name="uq_approval_step_chain_stage"),)

    chain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_chains.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[ApprovalStage] = enum_column(ApprovalStage, nullable=False)
    decision: Mapped[ApprovalDecision] = enum_column(
        ApprovalDecision, nullable=False, default=ApprovalDecision.PENDING
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    chain = relationship("ApprovalChain", back_populates="steps")

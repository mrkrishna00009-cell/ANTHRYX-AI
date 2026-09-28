"""M2/M4 extension - worker/community grievances.

A grievance is not a CAPA (no owner/severity ladder in the same sense)
but shares the same honest design principles: a real state machine, an
SLA measured from creation, and escalation that is an actual state
transition, not only a displayed countdown.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, UuidPkMixin, enum_column
from models.enums import GrievanceCategory, GrievanceStatus


class Grievance(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "grievances"

    mine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[GrievanceCategory] = enum_column(GrievanceCategory, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    filed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )  # NULL whenever is_anonymous is True - never store an identity we promised to hide
    status: Mapped[GrievanceStatus] = enum_column(
        GrievanceStatus, nullable=False, default=GrievanceStatus.OPEN, index=True
    )
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    escalation_level: Mapped[int] = mapped_column(default=0, nullable=False)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GrievanceEvent(UuidPkMixin, TimestampMixin, Base):
    """Every status change, mirroring CapaEvent's design exactly."""
    __tablename__ = "grievance_events"

    grievance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("grievances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[GrievanceStatus | None] = enum_column(GrievanceStatus, nullable=True)
    to_status: Mapped[GrievanceStatus] = enum_column(GrievanceStatus, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)

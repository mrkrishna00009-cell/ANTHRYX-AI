"""M4 - Corrective and preventive action, with escalation.

Detecting a problem is monitoring. Tracking it to verified closure is
management. An overdue CAPA is itself a risk signal and feeds back into
the risk inputs, which is what closes the loop.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, UuidPkMixin, enum_column
from models.enums import CapaSourceType, CapaStatus, Severity


class CapaItem(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "capa_items"

    mine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[CapaSourceType] = enum_column(
        CapaSourceType, nullable=False, index=True
    )
    # Polymorphic reference to the originating record. Deliberately not a
    # foreign key: the source may be an incident, an obligation breach or a
    # sensor anomaly, and a single FK cannot express that.
    source_id: Mapped[uuid.UUID | None] = mapped_column()
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("statutory_rules.id", ondelete="SET NULL"), index=True
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[Severity] = enum_column(Severity, nullable=False, index=True)
    status: Mapped[CapaStatus] = enum_column(
        CapaStatus, nullable=False, default=CapaStatus.OPEN, index=True
    )
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[date | None] = mapped_column(Date, index=True)

    closure_evidence_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events = relationship(
        "CapaEvent", back_populates="capa",
        cascade="all, delete-orphan", order_by="CapaEvent.created_at",
    )

    def is_overdue(self, today: date) -> bool:
        if self.due_date is None:
            return False
        if self.status in (CapaStatus.CLOSED, CapaStatus.VERIFIED):
            return False
        return self.due_date < today


class CapaEvent(UuidPkMixin, TimestampMixin, Base):
    """Every transition, with who did it and what evidence was attached."""

    __tablename__ = "capa_events"

    capa_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("capa_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[CapaStatus | None] = enum_column(CapaStatus, nullable=True)
    to_status: Mapped[CapaStatus] = enum_column(CapaStatus, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    evidence_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )

    capa = relationship("CapaItem", back_populates="events")

"""M0 - Statutory Rule Registry.

Compliance as code. The registry is what lets the system detect an
obligation that was never satisfied, not merely a document that expired.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, UuidPkMixin, enum_column
from models.enums import (
    ClauseVerification,
    ObligationStatus,
    ObligationType,
    Severity,
)


class StatutoryRule(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "statutory_rules"
    __table_args__ = (UniqueConstraint("rule_code", name="uq_statutory_rules_rule_code"),)

    rule_code: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    statute: Mapped[str] = mapped_column(String(160), nullable=False)
    clause: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    obligation_type: Mapped[ObligationType] = enum_column(ObligationType, nullable=False)
    frequency_days: Mapped[int | None] = mapped_column(Integer)
    applies_to_underground: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    applies_to_opencast: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    severity: Mapped[Severity] = enum_column(Severity, nullable=False, index=True)
    evidence_required: Mapped[str | None] = mapped_column(Text)
    authority: Mapped[str] = mapped_column(String(120), nullable=False, default="DGMS")

    # Clause references are seeded as a proof of concept and are not
    # authoritative until checked against the statute. The prototype does
    # not contain the full statutory corpus.
    clause_verification: Mapped[ClauseVerification] = enum_column(
        ClauseVerification, nullable=False, default=ClauseVerification.UNVERIFIED
    )
    source_reference: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    obligations = relationship("MineObligation", back_populates="rule")

    def applies_to(self, mine_type_value: str) -> bool:
        if mine_type_value == "UNDERGROUND":
            return self.applies_to_underground
        if mine_type_value == "OPENCAST":
            return self.applies_to_opencast
        return self.applies_to_underground or self.applies_to_opencast


class MineObligation(UuidPkMixin, TimestampMixin, Base):
    """One applicable rule bound to one mine, with its due state."""

    __tablename__ = "mine_obligations"
    __table_args__ = (
        UniqueConstraint("mine_id", "rule_id", name="uq_mine_obligations_mine_rule"),
    )

    mine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("statutory_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    last_satisfied_date: Mapped[date | None] = mapped_column(Date)
    next_due_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[ObligationStatus] = enum_column(
        ObligationStatus, nullable=False, default=ObligationStatus.MISSING, index=True
    )
    satisfying_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)

    mine = relationship("Mine", back_populates="obligations")
    rule = relationship("StatutoryRule", back_populates="obligations")

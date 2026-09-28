"""M6 - Statutory reporting, tamper-evident audit ledger, notifications."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from models.base import Base, TimestampMixin, UuidPkMixin, enum_column
from models.enums import NotificationChannel, ReportKind, Severity


class Report(UuidPkMixin, TimestampMixin, Base):
    """A generated statutory return.

    Until the official Form IV layout has been verified against the
    published form, output is labelled REPRESENTATIVE_STATUTORY_RETURN.
    Claiming official-form compliance without that check would be false.
    """

    __tablename__ = "reports"

    mine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ReportKind] = enum_column(ReportKind, nullable=False, index=True)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    file_path: Mapped[str | None] = mapped_column(Text)
    file_hash: Mapped[str | None] = mapped_column(String(64))
    official_format_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    payload: Mapped[dict | None] = mapped_column(JSON)


class AuditLogEntry(Base):
    """Append-only hash-chained ledger.

        row_hash = SHA256(seq | actor_id | action | entity_type |
                          entity_id | timestamp | payload_json | prev_hash)

    ``seq`` is inside the hash on purpose. Leaving it out would let rows be
    renumbered without breaking verification.

    This is tamper-EVIDENT, not immutable, and not a blockchain. It detects
    edits and deletions of interior rows. It does not prevent them, and a
    truncation of the newest rows cannot be detected by the chain alone -
    anchoring the head hash externally would address that, and is
    deployment scope rather than something quietly ignored here.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        UniqueConstraint("seq", name="uq_audit_log_seq"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class Notification(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mine_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[NotificationChannel] = enum_column(
        NotificationChannel, nullable=False, default=NotificationChannel.IN_APP
    )
    severity: Mapped[Severity] = enum_column(
        Severity, nullable=False, default=Severity.MEDIUM
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

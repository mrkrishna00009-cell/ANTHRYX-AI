"""M1 - Document intelligence, clearance lifecycle, and contractors.

Contractor tracking is an extension of this module rather than a separate
system: it reuses the same document and expiry lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, UuidPkMixin, enum_column
from models.enums import ContractorStatus, OcrEngine, VerificationStatus


class Document(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    mine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("statutory_rules.id", ondelete="SET NULL"), index=True
    )
    contractor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contractors.id", ondelete="SET NULL"), index=True
    )

    doc_type: Mapped[str] = mapped_column(String(120), nullable=False)
    certificate_no: Mapped[str | None] = mapped_column(String(160))
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date, index=True)

    file_path: Mapped[str | None] = mapped_column(Text)
    # SHA-256 of the stored file, so a later substitution is detectable.
    file_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    ocr_engine: Mapped[OcrEngine] = enum_column(
        OcrEngine, nullable=False, default=OcrEngine.NONE
    )
    ocr_confidence: Mapped[float | None] = mapped_column(Float)

    # OCR extraction is never compliance verification. A document only
    # satisfies an obligation once a human has verified it.
    verification_status: Mapped[VerificationStatus] = enum_column(
        VerificationStatus,
        nullable=False,
        default=VerificationStatus.PENDING_VERIFICATION,
        index=True,
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    fields = relationship(
        "ExtractedField", back_populates="document", cascade="all, delete-orphan"
    )


class ExtractedField(UuidPkMixin, TimestampMixin, Base):
    """One OCR-extracted field and the human correction applied to it.

    ``was_corrected`` is retained deliberately: it measures how often OCR
    was wrong, which is training signal for later and an honest quality
    metric now.
    """

    __tablename__ = "extracted_fields"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(120), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text)
    confirmed_value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    was_corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ocr_engine: Mapped[OcrEngine] = enum_column(
        OcrEngine, nullable=False, default=OcrEngine.NONE
    )

    document = relationship("Document", back_populates="fields")


class Contractor(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "contractors"
    __table_args__ = (UniqueConstraint("code", name="uq_contractors_code"),)

    code: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    trade: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[ContractorStatus] = enum_column(
        ContractorStatus, nullable=False, default=ContractorStatus.ACTIVE, index=True
    )
    registered_on: Mapped[date | None] = mapped_column(Date)

    sites = relationship(
        "ContractorSite", back_populates="contractor", cascade="all, delete-orphan"
    )


class ContractorSite(UuidPkMixin, TimestampMixin, Base):
    """A contractor's engagement at one mine, with its own validity window."""

    __tablename__ = "contractor_sites"
    __table_args__ = (
        UniqueConstraint("contractor_id", "mine_id", name="uq_contractor_sites_pair"),
    )

    contractor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contractors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_start: Mapped[date | None] = mapped_column(Date)
    contract_end: Mapped[date | None] = mapped_column(Date, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(Text)

    contractor = relationship("Contractor", back_populates="sites")

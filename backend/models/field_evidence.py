"""M2 - Field evidence captured offline and synced later.

Three record kinds share one envelope: inspection, attendance, incident.

The client clock is stored but never trusted. ``server_timestamp`` is
authoritative; ``client_timestamp`` exists so the skew between them is
visible and can be flagged.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from models.base import Base, TimestampMixin, UuidPkMixin, enum_column
from models.enums import (
    DataProvenance, EvidenceKind, IncidentSource, LocationMethod,
    ProviderStatus, Severity, SyncStatus,
)


class FieldEvidence(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "field_evidence"
    __table_args__ = (
        # The client generates this UUID before the record leaves the phone.
        # It is what makes a retried sync idempotent instead of duplicating.
        UniqueConstraint("client_uuid", name="uq_field_evidence_client_uuid"),
    )

    client_uuid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[EvidenceKind] = enum_column(EvidenceKind, nullable=False, index=True)

    mine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), index=True
    )

    client_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    server_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    clock_skew_seconds: Mapped[int | None] = mapped_column(Integer)

    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    gps_accuracy_m: Mapped[float | None] = mapped_column(Float)
    location_method: Mapped[LocationMethod] = enum_column(
        LocationMethod, nullable=False, default=LocationMethod.NONE
    )
    checkpoint_code: Mapped[str | None] = mapped_column(String(64))
    # Reported by the device where the platform exposes it. Absence is not
    # proof of authenticity; it is one signal among four.
    mock_location_reported: Mapped[bool | None] = mapped_column(Boolean)
    spoof_flags: Mapped[list | None] = mapped_column(JSON)

    photo_path: Mapped[str | None] = mapped_column(Text)
    photo_hash: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)

    sync_status: Mapped[SyncStatus] = enum_column(
        SyncStatus, nullable=False, default=SyncStatus.SYNCED, index=True
    )

    inspection = relationship(
        "InspectionFinding", back_populates="evidence", cascade="all, delete-orphan"
    )
    attendance = relationship(
        "AttendanceRecord", back_populates="evidence",
        cascade="all, delete-orphan", uselist=False,
    )
    incident = relationship(
        "IncidentReport", back_populates="evidence",
        cascade="all, delete-orphan", uselist=False,
    )


class InspectionFinding(UuidPkMixin, TimestampMixin, Base):
    """One checklist line. The checklist is driven by M0, not hardcoded."""

    __tablename__ = "inspection_findings"

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("field_evidence.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("statutory_rules.id", ondelete="SET NULL"), index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    compliant: Mapped[bool | None] = mapped_column(Boolean)
    severity: Mapped[Severity | None] = enum_column(Severity, nullable=True)
    observation: Mapped[str | None] = mapped_column(Text)

    evidence = relationship("FieldEvidence", back_populates="inspection")


class AttendanceRecord(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "attendance_records"

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("field_evidence.id", ondelete="CASCADE"), nullable=False, index=True
    )
    worker_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    contractor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contractors.id", ondelete="SET NULL"), index=True
    )
    shift: Mapped[str | None] = mapped_column(String(32))
    checked_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    evidence = relationship("FieldEvidence", back_populates="attendance")


class IncidentReport(UuidPkMixin, TimestampMixin, Base):
    """An incident, whether typed on a form or spoken into the phone.

    A voice incident is a normal incident record with ``source = VOICE``.
    The original audio, the source-language transcript and the English
    translation are all retained, along with which provider produced them -
    a demo-fallback transcript is never recorded as a live Bhashini result.
    """

    __tablename__ = "incident_reports"

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("field_evidence.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[Severity] = enum_column(Severity, nullable=False, index=True)
    description_en: Mapped[str | None] = mapped_column(Text)

    source: Mapped[IncidentSource] = enum_column(
        IncidentSource, nullable=False, default=IncidentSource.FORM, index=True
    )
    audio_path: Mapped[str | None] = mapped_column(Text)
    audio_hash: Mapped[str | None] = mapped_column(String(64))
    source_language: Mapped[str | None] = mapped_column(String(16))
    original_transcript: Mapped[str | None] = mapped_column(Text)
    translated_transcript: Mapped[str | None] = mapped_column(Text)
    asr_provider_status: Mapped[ProviderStatus | None] = enum_column(
        ProviderStatus, nullable=True
    )
    nmt_provider_status: Mapped[ProviderStatus | None] = enum_column(
        ProviderStatus, nullable=True
    )
    transcript_provenance: Mapped[DataProvenance | None] = enum_column(
        DataProvenance, nullable=True
    )

    evidence = relationship("FieldEvidence", back_populates="incident")

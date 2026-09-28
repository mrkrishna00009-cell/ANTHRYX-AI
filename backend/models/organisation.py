"""Subsidiaries, mines and registered field devices."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, UuidPkMixin, enum_column
from models.enums import DataProvenance, MineStatus, MineType


class Subsidiary(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "subsidiaries"
    __table_args__ = (UniqueConstraint("code", name="uq_subsidiaries_code"),)

    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str | None] = mapped_column(String(80))

    mines = relationship("Mine", back_populates="subsidiary")


class Mine(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "mines"
    __table_args__ = (UniqueConstraint("code", name="uq_mines_code"),)

    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    mine_type: Mapped[MineType] = enum_column(MineType, nullable=False, index=True)
    status: Mapped[MineStatus] = enum_column(
        MineStatus, nullable=False, default=MineStatus.ACTIVE, index=True
    )
    district: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(80))

    # Coordinates are approximate coalfield locations unless explicitly
    # surveyed. ``coordinate_provenance`` records which, so the map can
    # label them honestly rather than implying surveyed mine positions.
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    coordinate_is_approximate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    coordinate_provenance: Mapped[DataProvenance] = enum_column(
        DataProvenance, nullable=False, default=DataProvenance.DEMO
    )
    coordinate_note: Mapped[str | None] = mapped_column(Text)

    # M3 feature: retained per locked decision F6 (production_records table
    # was dropped; this scalar is a model input and survives).
    production_hours_last_year: Mapped[float | None] = mapped_column(Float)
    average_employee_count: Mapped[int | None] = mapped_column()

    # Set True whenever a CAPA closes for this mine (Phase 5 Part 3, Part
    # F). Closing a CAPA does not by itself change any of the feature
    # builder's live inputs under the current mapping, so this is an
    # honest "the current MlFeature row may be stale" signal rather than
    # an automatic re-score or a fabricated risk improvement. Cleared the
    # next time the feature builder actually runs for this mine.
    rescore_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Set True whenever a CAPA for this mine closes. Closing a CAPA never
    # fabricates an immediate risk improvement - it only marks that the
    # mine's feature row may now be stale and a human/operator should
    # rebuild features before trusting the last M3 score. Cleared when
    # the feature builder actually runs for this mine.
    rescore_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    subsidiary_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subsidiaries.id", ondelete="SET NULL"), index=True
    )
    subsidiary = relationship("Subsidiary", back_populates="mines")
    users = relationship(
        "User", back_populates="mine", foreign_keys="User.mine_id"
    )
    obligations = relationship("MineObligation", back_populates="mine")


class Device(UuidPkMixin, TimestampMixin, Base):
    """Registered field device, for M2 device binding.

    A submission from an unregistered device is not rejected outright; it is
    flagged. Rejecting would lose evidence, which is worse than flagging it.
    """

    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_devices_fingerprint"),)

    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(120))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

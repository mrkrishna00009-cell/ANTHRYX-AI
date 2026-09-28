"""M5 - Environmental telemetry.

Every reading carries its provenance. In the prototype that value is
SIMULATED: no physical sensor is connected, and the UI must say so
wherever these numbers appear.

This table stores readings only. The anomaly score computed from them is
an M5 artifact and lives in ``models.ml``; it is not an accident
probability and must never be displayed as one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, UuidPkMixin, enum_column
from models.enums import DataProvenance, SensorKind


class EnvironmentalReading(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "environmental_readings"
    __table_args__ = (
        Index("ix_env_readings_mine_time", "mine_id", "recorded_at"),
    )

    mine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sensor_kind: Mapped[SensorKind] = enum_column(SensorKind, nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location_label: Mapped[str | None] = mapped_column(String(120))

    provenance: Mapped[DataProvenance] = enum_column(
        DataProvenance, nullable=False, default=DataProvenance.SIMULATED, index=True
    )

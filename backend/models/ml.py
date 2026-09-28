"""Model inputs and outputs for M3 and M5.

M3 and M5 are separate systems sharing storage, not one system:

* ``MlPrediction`` with ``model_kind = ACCIDENT_RISK_SUPERVISED`` is a
  supervised estimate of whether a reportable accident occurs in the
  forward 12-month window.
* ``AnomalyExplanation`` with ``model_kind =
  SENSOR_ANOMALY_ISOLATION_FOREST`` is an unsupervised outlier score over
  simulated telemetry.

An anomaly score is not a probability of anything. The two are stored in
different tables, scored by different artifacts, and rendered on different
screens precisely so they cannot be confused.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from models.base import Base, TimestampMixin, UuidPkMixin, enum_column
from models.enums import DataProvenance, ModelKind, ModelStatus


class MlFeature(UuidPkMixin, TimestampMixin, Base):
    """One feature row for one mine over one closed window.

    Mirrors the MSHA training-table shape so the same feature contract
    serves training and inference. Features cover
    ``[window_end - 365d, window_end]``; a label, where one exists, covers
    ``(window_end, window_end + 365d]``. The two never overlap.
    """

    __tablename__ = "ml_features"
    __table_args__ = (
        UniqueConstraint("mine_id", "window_end_date", name="uq_ml_features_mine_window"),
        Index("ix_ml_features_window", "window_end_date"),
    )

    mine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    window_end_date: Mapped[date] = mapped_column(Date, nullable=False)

    violations_last_12m: Mapped[int | None] = mapped_column(Integer)
    ss_violations_last_12m: Mapped[int | None] = mapped_column(Integer)
    repeat_violation_ratio: Mapped[float | None] = mapped_column(Float)
    days_since_last_inspection: Mapped[int | None] = mapped_column(Integer)
    inspection_hours_last_12m: Mapped[float | None] = mapped_column(Float)
    avg_penalty_amount: Mapped[float | None] = mapped_column(Float)
    mine_size_avg_employees: Mapped[float | None] = mapped_column(Float)
    production_hours: Mapped[float | None] = mapped_column(Float)
    mine_type: Mapped[str | None] = mapped_column(String(32))

    # Compliance-side inputs. Overdue CAPA feeding back in is what makes
    # the system a loop rather than a one-way pipeline.
    expired_documents: Mapped[int | None] = mapped_column(Integer)
    overdue_obligations: Mapped[int | None] = mapped_column(Integer)
    overdue_capa_items: Mapped[int | None] = mapped_column(Integer)
    open_incidents: Mapped[int | None] = mapped_column(Integer)

    provenance: Mapped[DataProvenance] = enum_column(
        DataProvenance, nullable=False, default=DataProvenance.DEMO
    )


class MlPrediction(UuidPkMixin, TimestampMixin, Base):
    """M3 output. Never written by the M5 anomaly detector."""

    __tablename__ = "ml_predictions"
    __table_args__ = (Index("ix_ml_predictions_mine_kind", "mine_id", "model_kind"),)

    mine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Traceability: which exact MlFeature row this score was computed
    # from. Nullable because historical rows (written before this column
    # existed) have no way to be backfilled honestly - a NULL here means
    # "not recorded", never a fabricated guess at which feature row it was.
    feature_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ml_features.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_kind: Mapped[ModelKind] = enum_column(ModelKind, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # SHA-256 of the artifact that produced this score, so a prediction can
    # always be traced back to the exact model file.
    artifact_hash: Mapped[str | None] = mapped_column(String(64))

    score: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[str | None] = mapped_column(String(16))
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # SHAP attributions for tree models. Left null for a rule-based
    # baseline: fabricating SHAP output for a formula would be dishonest.
    explanation: Mapped[dict | None] = mapped_column(JSON)
    explanation_method: Mapped[str | None] = mapped_column(String(48))

    # A human may override the score, but must say why, and the override is
    # written to the audit ledger. The model orders a queue; it never decides.
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    override_score: Mapped[float | None] = mapped_column(Float)
    override_justification: Mapped[str | None] = mapped_column(Text)
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnomalyExplanation(UuidPkMixin, TimestampMixin, Base):
    """M5 output. Separate table, separate model, separate meaning."""

    __tablename__ = "anomaly_explanations"

    mine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_kind: Mapped[ModelKind] = enum_column(
        ModelKind, nullable=False, default=ModelKind.SENSOR_ANOMALY_ISOLATION_FOREST
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_hash: Mapped[str | None] = mapped_column(String(64))

    # Isolation Forest decision function. Lower is more anomalous. This is
    # an outlier score, not a probability and not a risk percentage.
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    is_anomaly: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    contributing_signals: Mapped[dict | None] = mapped_column(JSON)
    capa_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("capa_items.id", ondelete="SET NULL"), index=True
    )
    provenance: Mapped[DataProvenance] = enum_column(
        DataProvenance, nullable=False, default=DataProvenance.SIMULATED
    )


class ModelArtifactRecord(UuidPkMixin, TimestampMixin, Base):
    """What is actually on disk, and whether it is usable.

    Status is reported honestly: UNTRAINED means no model exists and no
    performance figure may be quoted for it.
    """

    __tablename__ = "model_artifacts"
    __table_args__ = (UniqueConstraint("model_kind", "version", name="uq_model_artifacts"),)

    model_kind: Mapped[ModelKind] = enum_column(ModelKind, nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ModelStatus] = enum_column(
        ModelStatus, nullable=False, default=ModelStatus.UNTRAINED
    )
    artifact_path: Mapped[str | None] = mapped_column(Text)
    artifact_hash: Mapped[str | None] = mapped_column(String(64))
    feature_schema: Mapped[dict | None] = mapped_column(JSON)
    # Populated only from a real evaluation run on real data. Never seeded.
    metrics: Mapped[dict | None] = mapped_column(JSON)
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

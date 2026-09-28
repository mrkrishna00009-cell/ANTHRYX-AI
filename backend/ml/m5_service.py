"""M5 - sensor anomaly scoring service.

Writes only to ``AnomalyExplanation``, never to ``MlPrediction``. Uses a
separate artifact, separate feature order, and separate vocabulary from
M3: ``anomaly_score`` / ``is_anomaly``, never ``risk_score`` or
``probability``. An anomaly, once detected, raises a CAPA item
(``source_type = SENSOR_ANOMALY``) rather than remaining an isolated
chart - it never writes to or reads from an ``MlPrediction`` row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import joblib
import numpy as np
from sqlalchemy import select

from ml import registry
from models.capa import CapaItem
from models.enums import CapaSourceType, CapaStatus, DataProvenance, ModelKind, SensorKind, Severity
from models.environment import EnvironmentalReading
from models.ml import AnomalyExplanation
from functools import lru_cache


class M5NotAvailable(RuntimeError):
    pass


@dataclass(frozen=True)
class M5Result:
    anomaly_score: float
    is_anomaly: bool
    contributing_signals: dict
    provenance_note: str = (
        "SIMULATED TELEMETRY. This is an unsupervised outlier score over "
        "simulated methane/CO/airflow readings, NOT an accident probability. "
        "Kept entirely separate from the M3 supervised risk score."
    )


class M5ScoringService:
    def __init__(self):
        info = registry.describe(ModelKind.SENSOR_ANOMALY_ISOLATION_FOREST)
        if info.status.value != "TRAINED":
            raise M5NotAvailable(info.detail)
        self.model = joblib.load(info.path)
        self.schema = info.feature_schema or {}
        self.feature_order: list[str] = self.schema.get(
            "feature_order", ["methane_pct", "co_ppm", "airflow_m3s"]
        )
        self.artifact_hash = info.sha256
        self.model_version = info.path

    def _vector(self, readings_by_kind: dict[SensorKind, float]) -> np.ndarray:
        key_map = {
            "methane_pct": SensorKind.METHANE,
            "co_ppm": SensorKind.CARBON_MONOXIDE,
            "airflow_m3s": SensorKind.AIRFLOW,
        }
        vec = [readings_by_kind.get(key_map[c]) for c in self.feature_order]
        if any(v is None for v in vec):
            missing = [c for c, v in zip(self.feature_order, vec) if v is None]
            raise ValueError(f"Missing required sensor readings for: {missing}")
        return np.array(vec, dtype=float).reshape(1, -1)

    def score_latest(self, session, mine_id) -> M5Result:
        """Scores the mine's most recent reading of each monitored signal."""
        latest: dict[SensorKind, float] = {}
        for kind in (SensorKind.METHANE, SensorKind.CARBON_MONOXIDE, SensorKind.AIRFLOW):
            row = session.execute(
                select(EnvironmentalReading)
                .where(EnvironmentalReading.mine_id == mine_id,
                       EnvironmentalReading.sensor_kind == kind)
                .order_by(EnvironmentalReading.recorded_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row is not None:
                latest[kind] = row.value

        X = self._vector(latest)
        score = float(self.model.decision_function(X)[0])
        is_anom = bool(self.model.predict(X)[0] == -1)
        contributing = {
            "methane_pct": X[0, 0], "co_ppm": X[0, 1], "airflow_m3s": X[0, 2],
            "note": "raw simulated readings scored, not individually thresholded - "
                   "the point of Isolation Forest is the multivariate combination",
        }
        return M5Result(anomaly_score=round(score, 5), is_anomaly=is_anom,
                        contributing_signals=contributing)

    def score_and_persist(self, session, mine_id, window_start: datetime,
                           window_end: datetime, raise_capa: bool = True):
        result = self.score_latest(session, mine_id)
        explanation = AnomalyExplanation(
            mine_id=mine_id,
            model_kind=ModelKind.SENSOR_ANOMALY_ISOLATION_FOREST,
            model_version=self.model_version,
            artifact_hash=self.artifact_hash,
            anomaly_score=result.anomaly_score,
            is_anomaly=int(result.is_anomaly),
            window_start=window_start, window_end=window_end,
            contributing_signals=result.contributing_signals,
            provenance=DataProvenance.SIMULATED,
        )
        session.add(explanation)
        session.flush()

        if raise_capa and result.is_anomaly:
            capa = CapaItem(
                mine_id=mine_id,
                source_type=CapaSourceType.SENSOR_ANOMALY,   # never RISK_ALERT - separation preserved
                severity=Severity.MEDIUM,
                description=(
                    f"M5 sensor-anomaly alert (score {result.anomaly_score}): an unusual "
                    f"combination of simulated methane/CO/airflow readings was detected. "
                    f"This is an outlier signal, not an accident-risk score."
                ),
                status=CapaStatus.OPEN,
                assigned_at=None, due_date=None, progress_percent=0,
            )
            session.add(capa)
            session.flush()
            explanation.capa_id = capa.id
            session.flush()

        return explanation


@lru_cache(maxsize=1)
def get_m5_scoring_service() -> "M5ScoringService":
    """The Isolation Forest artifact is deserialized once per process,
    not on every request. Safe to cache: the artifact does not change
    while the process runs."""
    return M5ScoringService()

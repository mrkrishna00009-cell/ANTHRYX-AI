"""M3 - supervised accident-risk scoring service.

Uses the Phase 3 model artifact exactly as delivered. Never retrains,
never alters the feature schema, never changes the label or temporal
split. Enforces the two Indian-deployment restrictions inherited from
Phase 3 unconditionally: ``production_hours`` and ``avg_penalty_amount``
are forced to NaN in deployable scoring, never accepted as caller-supplied
Indian values, never imputed.

M3 and M5 remain separate systems. This module writes only to
``MlPrediction`` and never to ``AnomalyExplanation``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import joblib
import numpy as np

from ml import registry
from models.enums import ModelKind
from models.ml import MlFeature, MlPrediction

RISK_CATEGORY_THRESHOLDS = {
    "LOW": (0.0, 0.482),
    "MEDIUM": (0.482, 0.70),
    "HIGH": (0.70, 1.0),
}

# Blocked for deployable (Indian) scoring, unconditionally. Neither is
# dropped from the model's input width - the artifact was fit on 9
# columns and cannot accept fewer. Both are forced to NaN instead.
DEPLOYABLE_BLOCKED_FEATURES = frozenset(
    {"production_hours", "avg_penalty_amount"}
)


class M3NotAvailable(RuntimeError):
    """Raised when no trained artifact exists. Never silently substituted."""


@dataclass(frozen=True)
class M3Result:
    risk_score: float
    risk_category: str
    model_version: str
    artifact_hash: str
    explanation: dict | None
    explanation_method: str | None
    vocabulary_note: str = (
        "M3 risk score - a ranking/prioritisation signal, not asserted as a "
        "calibrated accident probability outside the MSHA test population "
        "on which it was measured."
    )


class M3ScoringService:
    def __init__(self):
        info = registry.describe(ModelKind.ACCIDENT_RISK_SUPERVISED)
        if info.status.value != "TRAINED":
            raise M3NotAvailable(info.detail)
        self.model = joblib.load(info.path)
        self.schema = info.feature_schema or {}
        self.feature_order: list[str] = self.schema.get(
            "feature_order_msha_training",
            ["violations_last_12m", "ss_violations_last_12m", "repeat_violation_ratio",
             "days_since_last_inspection", "inspection_hours_last_12m",
             "avg_penalty_amount", "mine_size_avg_employees",
             "production_hours_msha_reference_only", "mine_type_binary"],
        )
        self.mine_type_encoding = self.schema.get(
            "mine_type_encoding", {"UNDERGROUND": 1.0, "OPENCAST": 0.0}
        )
        self.artifact_hash = info.sha256
        self.model_version = info.path
        if self.model.n_features_in_ != len(self.feature_order):
            raise M3NotAvailable(
                "Model/schema mismatch: artifact expects "
                f"{self.model.n_features_in_} features but the recorded "
                f"feature order has {len(self.feature_order)}."
            )

    def _vector(self, feature: MlFeature, mode: str) -> np.ndarray:
        source = {
            "violations_last_12m": feature.violations_last_12m,
            "ss_violations_last_12m": feature.ss_violations_last_12m,
            "repeat_violation_ratio": feature.repeat_violation_ratio,
            "days_since_last_inspection": feature.days_since_last_inspection,
            "inspection_hours_last_12m": feature.inspection_hours_last_12m,
            "avg_penalty_amount": feature.avg_penalty_amount,
            "mine_size_avg_employees": feature.mine_size_avg_employees,
            "production_hours_msha_reference_only": feature.production_hours,
            "mine_type": feature.mine_type,
        }
        vec = []
        for col in self.feature_order:
            raw_key = {
                "production_hours_msha_reference_only": "production_hours",
                "mine_type_binary": "mine_type",
            }.get(col, col)
            if mode == "deployable" and raw_key in DEPLOYABLE_BLOCKED_FEATURES:
                vec.append(np.nan)
                continue
            if col == "mine_type_binary":
                v = self.mine_type_encoding.get(source["mine_type"])
                v = np.nan if v is None else v
            else:
                v = source[raw_key]
                v = np.nan if v is None else float(v)
            vec.append(v)
        return np.array(vec, dtype=float).reshape(1, -1)

    def risk_category(self, score: float) -> str:
        for cat, (lo, hi) in RISK_CATEGORY_THRESHOLDS.items():
            if lo <= score < hi or (cat == "HIGH" and score == 1.0):
                return cat
        raise ValueError(f"score {score} matched no documented category")

    def explain(self, X: np.ndarray) -> tuple[dict | None, str | None]:
        """Real, model-native SHAP where available. Never fabricated - if
        SHAP cannot be computed, explanation is None, not an invented value."""
        try:
            import shap
            explainer = shap.TreeExplainer(self.model)
            values = explainer.shap_values(X)
            contributions = {
                col: round(float(v), 4) for col, v in zip(self.feature_order, values[0])
            }
            return contributions, "shap.TreeExplainer"
        except Exception:
            return None, None

    def score(self, feature: MlFeature, mode: str = "deployable",
              explain: bool = True) -> M3Result:
        X = self._vector(feature, mode=mode)
        score = float(self.model.predict_proba(X)[0, 1])
        category = self.risk_category(score)
        explanation, method = (self.explain(X) if explain else (None, None))
        return M3Result(
            risk_score=round(score, 4), risk_category=category,
            model_version=self.model_version, artifact_hash=self.artifact_hash,
            explanation=explanation, explanation_method=method,
        )

    def score_and_persist(self, session, feature: MlFeature,
                           mode: str = "deployable") -> MlPrediction:
        result = self.score(feature, mode=mode)
        prediction = MlPrediction(
            mine_id=feature.mine_id,
            feature_id=feature.id,
            model_kind=ModelKind.ACCIDENT_RISK_SUPERVISED,
            model_version=result.model_version,
            artifact_hash=result.artifact_hash,
            score=result.risk_score,
            band=result.risk_category,
            scored_at=datetime.now(timezone.utc),
            explanation=result.explanation,
            explanation_method=result.explanation_method,
        )
        session.add(prediction)
        session.flush()
        return prediction


@lru_cache(maxsize=1)
def get_m3_scoring_service() -> "M3ScoringService":
    """The joblib artifact is deserialized once per process, not on every
    request. Safe to cache: the artifact on disk does not change while
    the process runs, and this project never retrains M3 at request time."""
    return M3ScoringService()

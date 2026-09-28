"""Model artifact registry.

Reports what is on disk and refuses to imply more. If no artifact exists,
status is UNTRAINED and no score, metric or explanation is produced.

M3 and M5 artifacts are registered under different kinds and are never
interchangeable: a supervised accident-risk estimate and an unsupervised
sensor outlier score are different quantities.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.config import REPO_ROOT
from models.enums import ModelKind, ModelStatus

ARTIFACT_DIR = REPO_ROOT / "artifacts"

ARTIFACT_FILENAMES: dict[ModelKind, str] = {
    ModelKind.ACCIDENT_RISK_SUPERVISED: "accident_risk_model.joblib",
    ModelKind.SENSOR_ANOMALY_ISOLATION_FOREST: "isolation_forest.joblib",
}


@dataclass(frozen=True)
class ArtifactInfo:
    model_kind: ModelKind
    status: ModelStatus
    path: str | None
    sha256: str | None
    feature_schema: dict | None
    metrics: dict | None
    detail: str

    def as_dict(self) -> dict:
        return {
            "model_kind": self.model_kind.value,
            "status": self.status.value,
            "path": self.path,
            "sha256": self.sha256,
            "feature_schema": self.feature_schema,
            "metrics": self.metrics,
            "detail": self.detail,
        }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sidecar(path: Path, suffix: str) -> dict | None:
    candidate = path.with_name(path.stem + suffix)
    if not candidate.is_file():
        return None
    try:
        return json.loads(candidate.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def describe(model_kind: ModelKind) -> ArtifactInfo:
    filename = ARTIFACT_FILENAMES.get(model_kind)
    if filename is None:
        return ArtifactInfo(
            model_kind, ModelStatus.UNTRAINED, None, None, None, None,
            "No artifact is defined for this model kind.",
        )
    path = ARTIFACT_DIR / filename
    if not path.is_file():
        detail = (
            "No trained artifact on disk. The pipeline is ready and the "
            "feature contract is fixed, but nothing has been trained, so no "
            "score and no performance metric are available."
        )
        if model_kind is ModelKind.ACCIDENT_RISK_SUPERVISED:
            detail += " Supply the five MSHA archives to train."
        return ArtifactInfo(
            model_kind, ModelStatus.UNTRAINED, None, None, None, None, detail
        )
    return ArtifactInfo(
        model_kind, ModelStatus.TRAINED, str(path), _sha256(path),
        _sidecar(path, "_feature_schema.json"),
        _sidecar(path, "_metrics.json"),
        "Artifact present.",
    )


def registry_status() -> dict:
    return {
        kind.value: describe(kind).as_dict()
        for kind in (
            ModelKind.ACCIDENT_RISK_SUPERVISED,
            ModelKind.SENSOR_ANOMALY_ISOLATION_FOREST,
        )
    }

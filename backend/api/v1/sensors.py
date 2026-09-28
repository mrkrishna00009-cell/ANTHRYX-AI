"""M5 - environmental telemetry ingest and anomaly status.

Every reading is labelled with its provenance, which in the prototype is
SIMULATED. No physical sensor is connected and the API says so on every
response rather than leaving the caller to assume.

The anomaly score produced from these readings is an outlier score, not a
probability of an accident. It is deliberately kept apart from the M3
supervised risk score.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import assert_mine_access, get_current_user, require_any
from models.enums import DataProvenance, ModelKind, Role, SensorKind
from models.environment import EnvironmentalReading
from models.identity import User
from ml import registry
from schemas.common import NotImplementedNotice
from schemas.domain import ReadingIn, ReadingOut
from services.audit import AuditLedger

router = APIRouter(tags=["M5 sensor anomaly"])

INGESTORS = frozenset({Role.ADMIN, Role.MINE_MANAGER, Role.MINE_SAFETY_OFFICER})

SIMULATION_NOTICE = (
    "SIMULATED TELEMETRY. No physical sensor is connected to this system. "
    "In deployment these values would come from the mine's existing "
    "environmental monitoring installation. The contribution here is the "
    "multivariate analysis of that data, not the sensing."
)


@router.post("/sensors/readings", response_model=ReadingOut, status_code=201)
def ingest_reading(
    payload: ReadingIn,
    session: Session = Depends(get_db),
    actor: User = Depends(require_any(INGESTORS)),
):
    assert_mine_access(session, actor, payload.mine_id)
    reading = EnvironmentalReading(**payload.model_dump())
    session.add(reading)
    session.flush()
    return reading


@router.get("/sensors/readings", response_model=list[ReadingOut])
def list_readings(
    mine_id: uuid.UUID,
    sensor_kind: SensorKind | None = Query(default=None),
    limit: int = Query(default=200, le=2000),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    assert_mine_access(session, user, mine_id)
    stmt = (
        select(EnvironmentalReading)
        .where(EnvironmentalReading.mine_id == mine_id)
        .order_by(EnvironmentalReading.recorded_at.desc())
    )
    if sensor_kind:
        stmt = stmt.where(EnvironmentalReading.sensor_kind == sensor_kind)
    return list(session.execute(stmt.limit(limit)).scalars())


@router.get("/sensors/mines/{mine_id}/anomaly-history")
def anomaly_history(
    mine_id: uuid.UUID, session: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Every real AnomalyExplanation ever recorded for this mine, oldest
    first - mirrors risk.risk_history's design exactly, on the M5 side.
    Deliberately a SEPARATE endpoint, separate field names
    (anomaly_score/is_anomaly, never risk_score/risk_category), and
    SIMULATED provenance - never conflated with M3's risk history."""
    from models.ml import AnomalyExplanation
    assert_mine_access(session, user, mine_id)
    rows = session.execute(
        select(AnomalyExplanation).where(AnomalyExplanation.mine_id == mine_id)
        .order_by(AnomalyExplanation.window_end.asc())
    ).scalars().all()
    return [
        {"scored_at": r.window_end.isoformat(), "anomaly_score": r.anomaly_score,
        "is_anomaly": bool(r.is_anomaly), "provenance": r.provenance.value}
        for r in rows
    ]


@router.get("/sensors/status")
def sensor_status(user: User = Depends(get_current_user)):
    artifact = registry.describe(ModelKind.SENSOR_ANOMALY_ISOLATION_FOREST)
    return {
        "data_provenance": DataProvenance.SIMULATED.value,
        "physical_sensors_connected": False,
        "notice": SIMULATION_NOTICE,
        "monitored_signals": [k.value for k in SensorKind],
        "detector": {
            "algorithm": "IsolationForest",
            "model_kind": ModelKind.SENSOR_ANOMALY_ISOLATION_FOREST.value,
            "status": artifact.status.value,
            "detail": artifact.detail,
        },
        "separate_from_accident_risk": True,
        "separation_note": (
            "This anomaly score is an unsupervised outlier measure over "
            "telemetry. It is not an accident probability and is never "
            "presented as one. The supervised accident-risk score is M3."
        ),
    }


@router.post("/sensors/detect")
def detect(
    mine_id: uuid.UUID,
    session: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """Scores the mine's latest simulated readings with the Isolation
    Forest. Writes to AnomalyExplanation only - never to MlPrediction.
    An anomaly raises a CAPA (source_type=SENSOR_ANOMALY), never RISK_ALERT."""
    from datetime import datetime, timedelta, timezone
    from ml.m5_service import get_m5_scoring_service, M5NotAvailable

    assert_mine_access(session, actor, mine_id)
    try:
        service = get_m5_scoring_service()
    except M5NotAvailable as exc:
        notice = NotImplementedNotice(
            module="M5", capability="Isolation Forest multivariate anomaly detection",
            phase_planned="Phase 4", detail=str(exc),
            blocking_dependency="Trained isolation_forest.joblib artifact",
        )
        return JSONResponse(status_code=501, content=notice.model_dump(mode="json"))
    now = datetime.now(timezone.utc)
    try:
        explanation = service.score_and_persist(
            session, mine_id, window_start=now - timedelta(hours=1), window_end=now,
        )
    except ValueError as exc:
        notice = NotImplementedNotice(
            module="M5", capability="Isolation Forest multivariate anomaly detection",
            phase_planned="Phase 4", detail=str(exc),
            blocking_dependency="At least one EnvironmentalReading of each monitored signal",
        )
        return JSONResponse(status_code=501, content=notice.model_dump(mode="json"))
    AuditLedger(session).append(
        action="M5_ANOMALY_SCORED", entity_type="anomaly_explanation",
        entity_id=str(explanation.id), actor_id=str(actor.id),
        payload={"mine_id": str(mine_id), "anomaly_score": explanation.anomaly_score,
                "is_anomaly": bool(explanation.is_anomaly), "capa_id": str(explanation.capa_id)
                if explanation.capa_id else None},
    )
    return {
        "mine_id": str(mine_id),
        "anomaly_score": explanation.anomaly_score,
        "is_anomaly": bool(explanation.is_anomaly),
        "contributing_signals": explanation.contributing_signals,
        "capa_id": str(explanation.capa_id) if explanation.capa_id else None,
        "provenance": DataProvenance.SIMULATED.value,
        "separation_note": (
            "This is an unsupervised outlier score over simulated telemetry, "
            "not an accident probability. See M3 for the supervised risk score."
        ),
    }


@router.post("/sensors/simulate")
def simulate_telemetry(
    mine_id: uuid.UUID,
    mode: str = "normal",
    seed: int | None = None,
    session: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """Demo-only. Generates and persists three SIMULATED readings
    (methane/CO/airflow) for a mine, using the same generator shapes the
    Isolation Forest was trained on. Never claims physical sensor data,
    never invents a geographic coordinate. mode='normal' or 'anomaly';
    pass seed for a reproducible sequence."""
    from services.telemetry_simulator import generate_readings

    assert_mine_access(session, actor, mine_id)
    try:
        readings = generate_readings(mine_id, mode=mode, seed=seed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    created = []
    for r in readings:
        row = EnvironmentalReading(
            mine_id=mine_id, sensor_kind=r.sensor_kind, value=r.value, unit=r.unit,
            recorded_at=r.recorded_at, provenance=DataProvenance.SIMULATED,
        )
        session.add(row)
        created.append(row)
    session.flush()

    AuditLedger(session).append(
        action="M5_TELEMETRY_SIMULATED", entity_type="environmental_reading",
        entity_id=str(created[0].id) if created else None, actor_id=str(actor.id),
        payload={"mine_id": str(mine_id), "mode": mode, "seed": seed,
                "reading_ids": [str(r.id) for r in created]},
    )
    return {
        "mine_id": str(mine_id), "mode": mode, "seed": seed,
        "provenance": DataProvenance.SIMULATED.value,
        "readings": [
            {"sensor_kind": r.sensor_kind, "value": r.value, "unit": r.unit,
            "recorded_at": r.recorded_at.isoformat()} for r in created
        ],
        "note": (
            "SIMULATED telemetry for demonstration only. No physical sensor is "
            "connected. Run POST /sensors/detect next to score these readings."
        ),
    }

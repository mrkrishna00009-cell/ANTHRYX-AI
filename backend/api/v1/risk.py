"""M3 - supervised accident-risk intelligence.

No model has been trained, so no score is returned. The endpoints report
that state precisely rather than serving a placeholder number that would
later be mistaken for a result.

M3 answers: given this mine's compliance history to a cutoff date, does a
reportable accident occur in the following twelve months. That is a
different question, a different model and a different artifact from the
M5 sensor anomaly detector.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.database import get_db
from app.deps import get_current_user
from ml import registry
from ml.msha import schema as msha_schema
from models.enums import ModelKind
from models.identity import User
from schemas.common import NotImplementedNotice
from services.audit import AuditLedger

router = APIRouter(tags=["M3 risk intelligence"])


@router.get("/risk/model-status")
def model_status(user: User = Depends(get_current_user)):
    artifact = registry.describe(ModelKind.ACCIDENT_RISK_SUPERVISED)
    return {
        "model": artifact.as_dict(),
        "data_contract": msha_schema.contract_summary(),
        "metrics_available": artifact.metrics is not None,
        "reporting_policy": (
            "Plain accuracy is not a meaningful headline for a rare event. "
            "When the model is trained, evaluation reports Precision@K, "
            "PR-AUC and comparison against random selection and a "
            "highest-violation-count rule, on a strict date-cutoff temporal "
            "split. No figure is quoted before that run."
        ),
        "decision_policy": (
            "The model orders an inspection queue. It never makes an "
            "enforcement decision. A human may override any score with a "
            "written justification, and the override is written to the "
            "audit ledger."
        ),
    }


@router.get("/risk/separation")
def separation(user: User = Depends(get_current_user)):
    """Why M3 and M5 are not the same number."""
    return {
        "m3_accident_risk": {
            "model_kind": ModelKind.ACCIDENT_RISK_SUPERVISED.value,
            "learning": "supervised",
            "label": "reportable accident in the forward 12-month window",
            "inputs": "compliance history, inspection and violation record",
            "output": "calibrated risk estimate for inspection prioritisation",
        },
        "m5_sensor_anomaly": {
            "model_kind": ModelKind.SENSOR_ANOMALY_ISOLATION_FOREST.value,
            "learning": "unsupervised",
            "label": "none",
            "inputs": "simulated methane, carbon monoxide and airflow readings",
            "output": "outlier score for an unusual combination of readings",
        },
        "interchangeable": False,
        "note": (
            "Separate artifacts, separate tables, separate screens. An "
            "anomaly score is not a probability of an accident and must "
            "never be displayed as one."
        ),
    }


@router.post("/risk/mines/{mine_id}/build-features")
def build_features(
    mine_id: uuid.UUID,
    session=Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Constructs (or refreshes) today's MlFeature row for this mine from
    real application data - see services/feature_builder.py for the exact,
    documented mapping. Never uses MSHA rows, Q679/Q181, or a synthetic
    file. Safe to call repeatedly: idempotent on (mine_id, window_end_date)."""
    from app.deps import assert_mine_access
    from models.organisation import Mine
    from services.feature_builder import FeatureBuilder

    assert_mine_access(session, user, mine_id)
    builder = FeatureBuilder(session)
    try:
        row, availability = builder.build(mine_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    # availability.rescore_was_required reflects the flag's value BEFORE
    # build() cleared it - the correct point to read it. A second,
    # post-hoc read here would always see False, since build() already
    # cleared it internally.

    AuditLedger(session).append(
        action="M3_FEATURES_BUILT", entity_type="ml_feature",
        entity_id=str(row.id), actor_id=str(user.id),
        payload={"mine_id": str(mine_id), "window_end_date": row.window_end_date.isoformat()},
    )
    return {
        "mine_id": str(mine_id),
        "window_end_date": row.window_end_date.isoformat(),
        "feature_row_id": str(row.id),
        "violations_last_12m": row.violations_last_12m,
        "ss_violations_last_12m": row.ss_violations_last_12m,
        "repeat_violation_ratio": row.repeat_violation_ratio,
        "days_since_last_inspection": row.days_since_last_inspection,
        "inspection_hours_last_12m": row.inspection_hours_last_12m,
        "mine_size_avg_employees": row.mine_size_avg_employees,
        "mine_type": row.mine_type,
        "production_hours": row.production_hours,
        "avg_penalty_amount": row.avg_penalty_amount,
        "availability_notes": availability.notes,
        "rescore_was_required": availability.rescore_was_required,
        "rescore_was_pending": availability.rescore_was_required,
        "rescore_cleared": availability.rescore_was_required,
        "source": "built from real application data - see services/feature_builder.py mapping table",
    }


@router.get("/risk/mines/{mine_id}/history")
def risk_history(
    mine_id: uuid.UUID, session=Depends(get_db), user: User = Depends(get_current_user)
):
    """Every real MlPrediction ever recorded for this mine, oldest first -
    powers the risk trend chart. Whatever the count genuinely is (often
    just one, on a freshly bootstrapped mine) is what is returned; no
    synthetic point is ever added to make a trend look richer."""
    from app.deps import assert_mine_access
    from models.ml import MlPrediction
    from sqlalchemy import select
    assert_mine_access(session, user, mine_id)
    rows = session.execute(
        select(MlPrediction).where(MlPrediction.mine_id == mine_id).order_by(MlPrediction.scored_at.asc())
    ).scalars().all()
    return [
        {"scored_at": r.scored_at.isoformat(), "risk_score": r.score, "risk_category": r.band}
        for r in rows
    ]


@router.get("/risk/mines/{mine_id}")
def mine_risk(
    mine_id: uuid.UUID,
    window_end_date: str | None = None,
    session=Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Scores the mine's most recent MlFeature row (or the row for
    ``window_end_date`` if given) with the exact Phase 3 model artifact.
    Never retrains. Enforces the Indian-deployment blocked-feature policy
    inherited unmodified from Phase 3."""
    from sqlalchemy import select
    from app.deps import assert_mine_access
    from models.ml import MlFeature
    from models.organisation import Mine
    from ml.m3_service import get_m3_scoring_service, M3NotAvailable

    assert_mine_access(session, user, mine_id)
    stmt = select(MlFeature).where(MlFeature.mine_id == mine_id)
    if window_end_date:
        from datetime import date as _date
        stmt = stmt.where(MlFeature.window_end_date == _date.fromisoformat(window_end_date))
    else:
        stmt = stmt.order_by(MlFeature.window_end_date.desc())
    feature = session.execute(stmt.limit(1)).scalar_one_or_none()
    if feature is None:
        notice = NotImplementedNotice(
            module="M3", capability="Supervised accident-risk score",
            phase_planned="Phase 4",
            detail="No MlFeature row exists yet for this mine. Nothing is scored "
                   "or invented in its place.",
            blocking_dependency="An MlFeature row for this mine_id",
        )
        return JSONResponse(status_code=501, content=notice.model_dump(mode="json"))
    try:
        service = get_m3_scoring_service()
    except M3NotAvailable as exc:
        notice = NotImplementedNotice(
            module="M3", capability="Supervised accident-risk score",
            phase_planned="Phase 4", detail=str(exc),
            blocking_dependency="Trained accident_risk_model.joblib artifact",
        )
        return JSONResponse(status_code=501, content=notice.model_dump(mode="json"))
    prediction = service.score_and_persist(session, feature, mode="deployable")
    AuditLedger(session).append(
        action="M3_RISK_SCORED", entity_type="ml_prediction",
        entity_id=str(prediction.id), actor_id=str(user.id),
        payload={"mine_id": str(mine_id), "score": prediction.score, "band": prediction.band},
    )
    mine_for_flag = session.get(Mine, mine_id)
    rescore_required = bool(mine_for_flag.rescore_required) if mine_for_flag else False

    capa_id = None
    capa_created = False
    if prediction.band == "HIGH":
        from models.capa import CapaItem
        from models.enums import CapaSourceType, CapaStatus, Severity as SeverityEnum

        # Idempotent by design: a mine may have at most one ACTIVE (not
        # CLOSED) RISK_ALERT CAPA at a time. Refreshing the risk page never
        # creates a second one while the first is still open.
        existing_capa = session.execute(
            select(CapaItem).where(
                CapaItem.mine_id == mine_id,
                CapaItem.source_type == CapaSourceType.RISK_ALERT,
                CapaItem.status != CapaStatus.CLOSED,
            ).order_by(CapaItem.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        if existing_capa is not None:
            capa_id = existing_capa.id
        else:
            capa = CapaItem(
                mine_id=mine_id, source_type=CapaSourceType.RISK_ALERT,
                source_id=prediction.id, severity=SeverityEnum.HIGH,
                description=(
                    f"M3 risk-prioritised inspection suggestion: risk score "
                    f"{prediction.score} (HIGH). Ranking/prioritisation signal, "
                    f"not asserted as a calibrated accident probability."
                ),
                status=CapaStatus.OPEN,
            )
            session.add(capa)
            session.flush()
            AuditLedger(session).append(
                action="M3_AUTO_CAPA_CREATED", entity_type="capa_item",
                entity_id=str(capa.id), actor_id=str(user.id),
                payload={"mine_id": str(mine_id), "risk_score": prediction.score,
                        "prediction_id": str(prediction.id)},
            )
            capa_id = capa.id
            capa_created = True

    return {
        "mine_id": str(mine_id),
        "risk_score": prediction.score,
        "risk_category": prediction.band,
        "model_version": prediction.model_version,
        "artifact_hash": prediction.artifact_hash,
        "explanation": prediction.explanation,
        "explanation_method": prediction.explanation_method,
        "capa_created": capa_created,
        "capa_id": str(capa_id) if capa_id else None,
        "capa_note": (
            "A new RISK_ALERT CAPA was created for this HIGH-risk score." if capa_created
            else "An active RISK_ALERT CAPA already exists for this mine; none duplicated."
            if capa_id else "Risk category is not HIGH; no CAPA action taken."
        ),
        "vocabulary_note": (
            "M3 risk score - ranking/prioritisation signal, not asserted as a "
            "calibrated accident probability outside the MSHA test population."
        ),
        "rescore_required": rescore_required,
        "rescore_note": (
            "A CAPA for this mine closed since the features behind this score were "
            "last built. This score has NOT been artificially lowered to reflect that "
            "closure - it may now be stale. Call build-features to refresh it."
        ) if rescore_required else None,
        "decision_policy": "The model orders a queue. A human may override with justification.",
    }

"""Subsidiaries and mines."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import assert_mine_access, get_current_user, require_roles
from models.enums import DataProvenance, Role
from models.identity import User
from models.organisation import Mine, Subsidiary
from schemas.domain import MineCreate, MineOut, SubsidiaryOut
from services import rbac
from services.audit import AuditLedger

router = APIRouter(tags=["organisation"])


@router.get("/subsidiaries", response_model=list[SubsidiaryOut])
def list_subsidiaries(
    session: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return list(session.execute(select(Subsidiary).order_by(Subsidiary.name)).scalars())


@router.get("/mines/risk-overview")
def mines_risk_overview(
    session: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """One real, aggregated query per mine visible to this role: latest M3
    score/category, open+overdue CAPA counts, last inspection date. Powers
    the risk map and the alerts feed - never a per-mine round trip from
    the client, and never a fabricated number. M5 anomaly state is
    reported separately from risk_category and never used for map colour,
    preserving the M3/M5 separation."""
    from datetime import date
    from models.capa import CapaItem
    from models.enums import CapaStatus, EvidenceKind
    from models.field_evidence import FieldEvidence
    from models.ml import MlPrediction, AnomalyExplanation

    mines = list(session.execute(select(Mine).order_by(Mine.name)).scalars())
    visible = [
        m for m in mines
        if rbac.can_access_mine(user.role, user.mine_id, user.subsidiary_id, m.id, m.subsidiary_id)
    ]

    overview = []
    for mine in visible:
        latest_pred = session.execute(
            select(MlPrediction).where(MlPrediction.mine_id == mine.id)
            .order_by(MlPrediction.scored_at.desc()).limit(1)
        ).scalar_one_or_none()

        open_capas = session.execute(
            select(CapaItem).where(CapaItem.mine_id == mine.id, CapaItem.status != CapaStatus.CLOSED)
        ).scalars().all()
        overdue = [c for c in open_capas if c.due_date and c.due_date < date.today()]

        last_inspection = session.execute(
            select(FieldEvidence.server_timestamp).where(
                FieldEvidence.mine_id == mine.id, FieldEvidence.kind == EvidenceKind.INSPECTION
            ).order_by(FieldEvidence.server_timestamp.desc()).limit(1)
        ).scalar_one_or_none()

        latest_anomaly = session.execute(
            select(AnomalyExplanation).where(AnomalyExplanation.mine_id == mine.id)
            .order_by(AnomalyExplanation.window_end.desc()).limit(1)
        ).scalar_one_or_none()

        overview.append({
            "mine_id": str(mine.id), "name": mine.name, "code": mine.code,
            "latitude": mine.latitude, "longitude": mine.longitude,
            "coordinate_is_approximate": mine.coordinate_is_approximate,
            "coordinate_provenance": mine.coordinate_provenance.value if mine.coordinate_provenance else None,
            "risk_score": latest_pred.score if latest_pred else None,
            "risk_category": latest_pred.band if latest_pred else None,
            "risk_scored_at": latest_pred.scored_at.isoformat() if latest_pred else None,
            "explanation": latest_pred.explanation if latest_pred else None,
            "rescore_required": bool(mine.rescore_required),
            "open_capa_count": len(open_capas),
            "overdue_capa_count": len(overdue),
            "last_inspection_at": last_inspection.isoformat() if last_inspection else None,
            "m5_is_anomaly": bool(latest_anomaly.is_anomaly) if latest_anomaly else None,
            "m5_anomaly_score": latest_anomaly.anomaly_score if latest_anomaly else None,
        })
    return overview


@router.get("/mines/{mine_id}/timeline")
def mine_timeline(
    mine_id: uuid.UUID, limit: int = 200,
    session: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Real chronological event aggregation - see services/mine_timeline.py
    for the exact source tables. Every event is read from a table another,
    already-verified module wrote to; nothing here is invented."""
    from services.mine_timeline import build_timeline

    assert_mine_access(session, user, mine_id)
    events = build_timeline(session, mine_id, limit=limit)
    return {
        "mine_id": str(mine_id),
        "event_count": len(events),
        "events": [
            {
                "timestamp": e.timestamp.isoformat(), "event_type": e.event_type,
                "severity": e.severity, "source": e.source, "actor_id": e.actor_id,
                "status": e.status, "related_id": e.related_id, "explanation": e.explanation,
            }
            for e in events
        ],
        "note": (
            "Aggregated from real persisted records across M0/M2/M3/M4/M5/Grievances - "
            "never a separate event log, never a fabricated entry. An empty list means "
            "this mine genuinely has no recorded events yet."
        ),
    }


@router.get("/mines/{mine_id}/contradictions")
def mine_contradictions(
    mine_id: uuid.UUID, session: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Real, on-demand contradiction/drift detection - see
    services/contradiction_drift.py for the single, deliberately narrow
    rule this implements (document-recorded compliance vs. the most
    recent field-observed compliance for the same rule). Never a
    fabricated example; an empty list means no contradiction was found,
    not that detection didn't run."""
    from services.contradiction_drift import detect_contradictions

    assert_mine_access(session, user, mine_id)
    found = detect_contradictions(session, mine_id)
    return {
        "mine_id": str(mine_id),
        "contradiction_count": len(found),
        "contradictions": [
            {
                "contradiction_type": c.contradiction_type, "rule_code": c.rule_code,
                "severity": c.severity, "contradiction_confidence": c.contradiction_confidence,
                "obligation_status": c.obligation_status,
                "obligation_last_satisfied_date": c.obligation_last_satisfied_date,
                "finding_id": c.finding_id, "finding_observed_at": c.finding_observed_at,
                "finding_observation": c.finding_observation, "explanation": c.explanation,
            }
            for c in found
        ],
        "detector_coverage": (
            "This endpoint currently detects two contradiction types: (1) a document-recorded "
            "obligation status that disagrees with the most recent field-observed compliance for "
            "the same rule, and (2) a mine's own inspection history reversing from compliant to "
            "non-compliant across two real inspections of the same rule. A third candidate (a "
            "statutory rule's own definition changing version over time) is not implemented - this "
            "schema has no rule-version history table, so detecting it would require inventing a "
            "prior version that was never actually recorded."
        ),
        "vocabulary_note": (
            "severity and contradiction_confidence are this detector's own vocabulary - "
            "never the same scale as M3 risk_score/risk_category or M5 anomaly_score/is_anomaly."
        ),
    }


@router.get("/mines", response_model=list[MineOut])
def list_mines(
    session: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Scoped to what the caller's role may see."""
    mines = list(session.execute(select(Mine).order_by(Mine.name)).scalars())
    return [
        m for m in mines
        if rbac.can_access_mine(
            user.role, user.mine_id, user.subsidiary_id, m.id, m.subsidiary_id
        )
    ]


@router.get("/mines/{mine_id}", response_model=MineOut)
def get_mine(
    mine_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return assert_mine_access(session, user, mine_id)


@router.post("/mines", response_model=MineOut, status_code=201)
def create_mine(
    payload: MineCreate,
    session: Session = Depends(get_db),
    actor: User = Depends(require_roles(Role.ADMIN, Role.DGMS_REGULATOR)),
):
    if session.execute(
        select(Mine).where(Mine.code == payload.code)
    ).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Mine code already exists")

    mine = Mine(
        **payload.model_dump(exclude={"coordinate_is_approximate"}),
        coordinate_is_approximate=payload.coordinate_is_approximate,
        # Coordinates supplied through the API are user-supplied, not
        # surveyed. The map labels them accordingly.
        coordinate_provenance=DataProvenance.USER_SUPPLIED,
    )
    session.add(mine)
    session.flush()
    AuditLedger(session).append(
        action="MINE_CREATED", entity_type="mine", entity_id=str(mine.id),
        actor_id=str(actor.id), payload={"code": mine.code},
    )
    return mine


@router.get("/mines/{mine_id}/checklist")
def inspection_checklist(
    mine_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The M0 rules genuinely applicable to this mine's type, shaped as
    checklist items for the PWA inspection form. Not hardcoded: driven
    entirely by StatutoryRule rows filtered on the mine's real mine_type,
    the same rule set M0's obligation tracking already uses."""
    from models.statutory import StatutoryRule

    mine = assert_mine_access(session, user, mine_id)
    applies_col = (
        StatutoryRule.applies_to_underground if mine.mine_type.value == "UNDERGROUND"
        else StatutoryRule.applies_to_opencast
    )
    rules = session.execute(
        select(StatutoryRule).where(applies_col.is_(True)).order_by(StatutoryRule.severity.desc(), StatutoryRule.title)
    ).scalars().all()

    return {
        "mine_id": str(mine_id),
        "mine_type": mine.mine_type.value,
        "checklist": [
            {
                "rule_id": str(r.id),
                "rule_code": r.rule_code,
                "statute": r.statute,
                "clause": r.clause,
                "question": f"Compliant with {r.statute} {r.clause}: {r.title}?",
                "severity": r.severity.value,
                "evidence_required": r.evidence_required,
                "clause_verification": r.clause_verification.value,
            }
            for r in rules
        ],
        "note": "Checklist items are the M0 statutory rules applicable to this mine's "
               "type. Clause references are seeded as proof-of-concept and are not "
               "authoritative until independently verified against the statute.",
    }

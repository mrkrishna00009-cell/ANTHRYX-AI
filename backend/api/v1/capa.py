"""M4 - CAPA lifecycle and escalation."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import assert_mine_access, get_current_user, require_any
from models.capa import CapaItem
from models.enums import CapaStatus, Role
from models.identity import User
from models.organisation import Mine
from schemas.domain import CapaCreate, CapaEventOut, CapaOut, CapaTransition
from services import capa as capa_service
from services import rbac
from services.audit import AuditLedger

router = APIRouter(tags=["M4 CAPA"])

ASSIGNERS = rbac.VERIFIERS | {Role.DGMS_REGULATOR, Role.SUBSIDIARY_HEAD}


@router.get("/capa", response_model=list[CapaOut])
def list_capa(
    mine_id: uuid.UUID | None = None,
    status_filter: CapaStatus | None = Query(default=None, alias="status"),
    overdue_only: bool = False,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(CapaItem).order_by(CapaItem.due_date.asc().nulls_last())
    if mine_id:
        assert_mine_access(session, user, mine_id)
        stmt = stmt.where(CapaItem.mine_id == mine_id)
    if status_filter:
        stmt = stmt.where(CapaItem.status == status_filter)
    items = list(session.execute(stmt).scalars())
    if overdue_only:
        today = date.today()
        items = [i for i in items if i.is_overdue(today)]
    return items


@router.post("/capa", response_model=CapaOut, status_code=201)
def create_capa(
    payload: CapaCreate,
    session: Session = Depends(get_db),
    actor: User = Depends(require_any(ASSIGNERS)),
):
    assert_mine_access(session, actor, payload.mine_id)
    item = CapaItem(**payload.model_dump(), status=CapaStatus.OPEN)
    if payload.assigned_to:
        item.assigned_at = datetime.now(timezone.utc)
    session.add(item)
    session.flush()
    AuditLedger(session).append(
        action="CAPA_CREATED", entity_type="capa_item", entity_id=str(item.id),
        actor_id=str(actor.id),
        payload={
            "source_type": item.source_type.value,
            "severity": item.severity.value,
            "due_date": item.due_date.isoformat() if item.due_date else None,
        },
    )
    return item


@router.post("/capa/{capa_id}/transition", response_model=CapaOut)
def transition_capa(
    capa_id: uuid.UUID,
    payload: CapaTransition,
    session: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    item = session.get(CapaItem, capa_id)
    if item is None:
        raise HTTPException(status_code=404, detail="CAPA item not found")
    assert_mine_access(session, actor, item.mine_id)

    # Closing out is a verification act and is restricted accordingly.
    if payload.to_status in (CapaStatus.VERIFIED, CapaStatus.CLOSED):
        if not rbac.has_role(actor.role, rbac.VERIFIERS):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Only a mine manager, safety officer or administrator may "
                    "verify or close a corrective action."
                ),
            )

    try:
        event = capa_service.transition(
            session, item, payload.to_status, actor_id=actor.id,
            note=payload.note, evidence_doc_id=payload.evidence_doc_id,
            progress_percent=payload.progress_percent,
        )
    except capa_service.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if payload.to_status is CapaStatus.CLOSED:
        # A closed CAPA never fabricates an immediate risk improvement.
        # It only marks the mine's feature row as possibly stale; a real
        # rebuild (POST /risk/mines/{id}/build-features) must run before
        # any new score reflects this closure.
        mine = session.get(Mine, item.mine_id)
        if mine is not None:
            mine.rescore_required = True
            session.flush()

    AuditLedger(session).append(
        action="CAPA_TRANSITION", entity_type="capa_item", entity_id=str(item.id),
        actor_id=str(actor.id),
        payload={
            "from": event.from_status.value if event.from_status else None,
            "to": event.to_status.value,
            "note_present": bool(payload.note),
        },
    )

    if payload.to_status is CapaStatus.CLOSED:
        # Closing a CAPA never itself changes a feature-builder input under
        # the current mapping (CAPA status is not one of the 7 live
        # features), so this is an honest "re-evaluate this mine" flag,
        # never a fabricated automatic risk improvement.
        mine = session.get(Mine, item.mine_id)
        if mine is not None and not mine.rescore_required:
            mine.rescore_required = True
            session.flush()
            AuditLedger(session).append(
                action="MINE_RESCORE_REQUIRED", entity_type="mine", entity_id=str(mine.id),
                actor_id=str(actor.id),
                payload={"reason": "CAPA closed", "capa_id": str(item.id)},
            )

    return item


@router.get("/capa/{capa_id}/events", response_model=list[CapaEventOut])
def capa_events(
    capa_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = session.get(CapaItem, capa_id)
    if item is None:
        raise HTTPException(status_code=404, detail="CAPA item not found")
    assert_mine_access(session, user, item.mine_id)
    return item.events


@router.get("/capa/escalation/ladder")
def escalation_ladder(user: User = Depends(get_current_user)):
    return {
        "ladder": [
            {
                "level": r.level,
                "days_relative_to_due": r.days_relative_to_due,
                "notify_role": r.notify_role,
                "description": r.description,
            }
            for r in capa_service.DEFAULT_ESCALATION_LADDER
        ],
        "scheduler_running": False,
        "scheduler_phase_planned": "Phase 6",
        "note": (
            "The ladder is evaluated on demand. The scheduled job that walks "
            "it daily is not running yet, so escalation levels are computed "
            "rather than pushed."
        ),
    }


@router.get("/capa/escalation/due")
def escalation_due(
    session: Session = Depends(get_db),
    user: User = Depends(require_any(ASSIGNERS)),
):
    """Which items have reached which rung, computed now."""
    today = date.today()
    rows = []
    for item in session.execute(select(CapaItem)).scalars():
        level = capa_service.due_escalation_level(item, today)
        if level > item.escalation_level:
            rows.append({
                "capa_id": str(item.id),
                "mine_id": str(item.mine_id),
                "severity": item.severity.value,
                "status": item.status.value,
                "due_date": item.due_date.isoformat() if item.due_date else None,
                "current_level": item.escalation_level,
                "due_level": level,
            })
    return {"as_of": today.isoformat(), "items": rows}

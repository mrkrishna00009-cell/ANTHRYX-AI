"""M2/M4 extension - worker/community grievances.

File -> tracked with a real SLA deadline -> transitioned through a real
state machine -> escalated (a real state change, mirroring
services/escalation_scheduler.py's design exactly) when the SLA is
breached -> resolved with a note.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import assert_mine_access, get_current_user
from models.enums import GrievanceCategory, GrievanceStatus
from models.grievance import Grievance, GrievanceEvent
from models.identity import User
from services.audit import AuditLedger

router = APIRouter(tags=["grievances"])


def _aware(dt: datetime) -> datetime:
    """SQLite silently drops tzinfo even on a DateTime(timezone=True)
    column; PostgreSQL does not. Normalise defensively so SLA arithmetic
    works identically on both, rather than assuming one database's
    behaviour - the same fix applied in api/v1/approvals.py."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


ALLOWED_TRANSITIONS = {
    GrievanceStatus.OPEN: {GrievanceStatus.IN_PROGRESS, GrievanceStatus.ESCALATED, GrievanceStatus.RESOLVED},
    GrievanceStatus.IN_PROGRESS: {GrievanceStatus.RESOLVED, GrievanceStatus.ESCALATED},
    GrievanceStatus.ESCALATED: {GrievanceStatus.IN_PROGRESS, GrievanceStatus.RESOLVED},
    GrievanceStatus.RESOLVED: set(),
}


class GrievanceIn(BaseModel):
    mine_id: uuid.UUID
    category: GrievanceCategory
    description: str
    is_anonymous: bool = False


class GrievanceTransitionIn(BaseModel):
    to_status: GrievanceStatus
    note: str | None = None


@router.post("/grievances", status_code=201)
def file_grievance(
    payload: GrievanceIn, session: Session = Depends(get_db), actor: User = Depends(get_current_user)
):
    mine = assert_mine_access(session, actor, payload.mine_id)
    settings = get_settings()
    sla_due_at = datetime.now(timezone.utc) + timedelta(days=settings.grievance_sla_days)

    g = Grievance(
        mine_id=mine.id, category=payload.category, description=payload.description,
        is_anonymous=payload.is_anonymous,
        filed_by=None if payload.is_anonymous else actor.id,  # never store identity behind an anonymity promise
        status=GrievanceStatus.OPEN, sla_due_at=sla_due_at,
    )
    session.add(g)
    session.flush()
    session.add(GrievanceEvent(grievance_id=g.id, from_status=None, to_status=GrievanceStatus.OPEN,
                               actor_id=None if payload.is_anonymous else actor.id))
    session.flush()

    AuditLedger(session).append(
        action="GRIEVANCE_FILED", entity_type="grievance", entity_id=str(g.id),
        actor_id=None if payload.is_anonymous else str(actor.id),
        payload={"mine_id": str(mine.id), "category": payload.category.value, "anonymous": payload.is_anonymous},
    )
    return _out(g)


@router.get("/grievances")
def list_grievances(
    mine_id: uuid.UUID | None = None,
    status: GrievanceStatus | None = None,
    category: GrievanceCategory | None = None,
    session: Session = Depends(get_db), actor: User = Depends(get_current_user)
):
    stmt = select(Grievance)
    if mine_id is not None:
        assert_mine_access(session, actor, mine_id)
        stmt = stmt.where(Grievance.mine_id == mine_id)
    if status is not None:
        stmt = stmt.where(Grievance.status == status)
    if category is not None:
        stmt = stmt.where(Grievance.category == category)
    rows = session.execute(stmt.order_by(Grievance.created_at.desc())).scalars().all()

    if mine_id is None:
        from models.organisation import Mine
        from services import rbac
        mine_cache = {m.id: m for m in session.execute(select(Mine)).scalars().all()}
        rows = [
            r for r in rows
            if r.mine_id in mine_cache and rbac.can_access_mine(
                actor.role, actor.mine_id, actor.subsidiary_id,
                mine_cache[r.mine_id].id, mine_cache[r.mine_id].subsidiary_id,
            )
        ]
    return [_out(g) for g in rows]


@router.post("/grievances/{grievance_id}/transition")
def transition_grievance(
    grievance_id: uuid.UUID, payload: GrievanceTransitionIn,
    session: Session = Depends(get_db), actor: User = Depends(get_current_user)
):
    g = session.get(Grievance, grievance_id)
    if g is None:
        raise HTTPException(status_code=404, detail="Grievance not found")
    assert_mine_access(session, actor, g.mine_id)

    if payload.to_status not in ALLOWED_TRANSITIONS[g.status]:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move a grievance from {g.status.value} to {payload.to_status.value}",
        )
    if payload.to_status == GrievanceStatus.RESOLVED and not payload.note:
        raise HTTPException(status_code=422, detail="A resolution note is required to resolve a grievance")

    from_status = g.status
    g.status = payload.to_status
    if payload.to_status == GrievanceStatus.RESOLVED:
        g.resolution_note = payload.note
        g.resolved_at = datetime.now(timezone.utc)
    session.add(GrievanceEvent(grievance_id=g.id, from_status=from_status, to_status=payload.to_status,
                               actor_id=actor.id, note=payload.note))
    session.flush()

    AuditLedger(session).append(
        action="GRIEVANCE_TRANSITION", entity_type="grievance", entity_id=str(g.id),
        actor_id=str(actor.id),
        payload={"from": from_status.value, "to": payload.to_status.value, "note_present": bool(payload.note)},
    )
    return _out(g)


def run_sla_check(session: Session, now: datetime | None = None) -> list[dict]:
    """Deterministic, directly callable SLA-breach check - same design as
    services/escalation_scheduler.run_escalation_check: idempotent (only
    acts on a grievance not already ESCALATED/RESOLVED), a real state
    change, a real audit entry, safe to run any number of times."""
    now = now or datetime.now(timezone.utc)
    results = []
    breached = session.execute(
        select(Grievance).where(
            Grievance.status.in_([GrievanceStatus.OPEN, GrievanceStatus.IN_PROGRESS]),
        )
    ).scalars().all()
    breached = [g for g in breached if _aware(g.sla_due_at) < now]
    for g in breached:
        from_status = g.status
        g.status = GrievanceStatus.ESCALATED
        g.escalation_level += 1
        session.add(GrievanceEvent(
            grievance_id=g.id, from_status=from_status, to_status=GrievanceStatus.ESCALATED,
            actor_id=None, note=f"[SYSTEM_SLA_CHECK] SLA breached (due {g.sla_due_at.isoformat()}).",
        ))
        session.flush()
        AuditLedger(session).append(
            action="GRIEVANCE_SLA_ESCALATED", entity_type="grievance", entity_id=str(g.id),
            actor_id=None, payload={"mine_id": str(g.mine_id), "sla_due_at": g.sla_due_at.isoformat()},
        )
        results.append({"grievance_id": str(g.id), "escalation_level": g.escalation_level})
    return results


@router.post("/grievances/run-sla-check")
def trigger_sla_check(session: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """UI-triggerable equivalent of a production scheduler tick - the
    prototype's deterministic stand-in, explicitly labelled as such."""
    results = run_sla_check(session)
    return {"escalated": results, "note": "Deterministic SLA check - stands in for a production scheduler tick."}


def _out(g: Grievance) -> dict:
    now = datetime.now(timezone.utc)
    due = _aware(g.sla_due_at)
    days_overdue = (now - due).days if now > due else None
    return {
        "id": str(g.id), "mine_id": str(g.mine_id), "category": g.category.value,
        "description": g.description, "is_anonymous": g.is_anonymous,
        "status": g.status.value, "sla_due_at": g.sla_due_at.isoformat(),
        "sla_breached": now > due and g.status != GrievanceStatus.RESOLVED,
        "days_overdue": days_overdue, "escalation_level": g.escalation_level,
        "resolution_note": g.resolution_note,
        "resolved_at": g.resolved_at.isoformat() if g.resolved_at else None,
        "created_at": g.created_at.isoformat(),
    }

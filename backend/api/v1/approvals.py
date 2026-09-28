"""M4 extension - a three-stage approval chain for a CAPA that needs
sign-off above the mine level.

Stage order is fixed: MINE_MANAGER -> SUBSIDIARY_GM -> CORPORATE_OFFICE.
A stage can only be decided once every earlier stage is APPROVED. A
REJECTED decision at any stage ends the chain there - the request does
not silently advance past a rejection.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import assert_mine_access, get_current_user
from models.approval import STAGE_ORDER, ApprovalChain, ApprovalStep
from models.capa import CapaItem
from models.enums import ApprovalDecision
from models.identity import User
from services.audit import AuditLedger

router = APIRouter(tags=["approvals"])


class ApprovalRequestIn(BaseModel):
    capa_id: uuid.UUID
    reason: str


class ApprovalDecisionIn(BaseModel):
    decision: ApprovalDecision  # APPROVED or REJECTED
    note: str | None = None


@router.post("/approvals", status_code=201)
def request_approval(
    payload: ApprovalRequestIn, session: Session = Depends(get_db), actor: User = Depends(get_current_user)
):
    capa = session.get(CapaItem, payload.capa_id)
    if capa is None:
        raise HTTPException(status_code=404, detail="CAPA not found")
    assert_mine_access(session, actor, capa.mine_id)

    existing = session.execute(
        select(ApprovalChain).where(ApprovalChain.capa_id == payload.capa_id)
    ).scalar_one_or_none()
    if existing is not None:
        return _out(session, existing)

    chain = ApprovalChain(capa_id=capa.id, requested_by=actor.id, reason=payload.reason)
    session.add(chain)
    session.flush()
    for i, stage in enumerate(STAGE_ORDER):
        session.add(ApprovalStep(chain_id=chain.id, sequence=i, stage=stage))
    session.flush()

    AuditLedger(session).append(
        action="APPROVAL_CHAIN_CREATED", entity_type="approval_chain", entity_id=str(chain.id),
        actor_id=str(actor.id), payload={"capa_id": str(capa.id), "reason": payload.reason},
    )
    return _out(session, chain)


@router.get("/approvals")
def list_approvals(session: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    chains = session.execute(select(ApprovalChain).order_by(ApprovalChain.created_at.desc())).scalars().all()
    visible = []
    for c in chains:
        capa = session.get(CapaItem, c.capa_id)
        if capa is None:
            continue
        try:
            assert_mine_access(session, actor, capa.mine_id)
        except HTTPException:
            continue
        visible.append(_out(session, c))
    return visible


@router.post("/approvals/{chain_id}/decide")
def decide_stage(
    chain_id: uuid.UUID, payload: ApprovalDecisionIn,
    session: Session = Depends(get_db), actor: User = Depends(get_current_user)
):
    chain = session.get(ApprovalChain, chain_id)
    if chain is None:
        raise HTTPException(status_code=404, detail="Approval chain not found")
    capa = session.get(CapaItem, chain.capa_id)
    assert_mine_access(session, actor, capa.mine_id)

    if chain.final_decision != ApprovalDecision.PENDING:
        raise HTTPException(status_code=409, detail=f"This chain already reached a final decision: {chain.final_decision.value}")
    if payload.decision == ApprovalDecision.PENDING:
        raise HTTPException(status_code=422, detail="decision must be APPROVED or REJECTED")

    steps = sorted(chain.steps, key=lambda s: s.sequence)
    current = next((s for s in steps if s.decision == ApprovalDecision.PENDING), None)
    if current is None:
        raise HTTPException(status_code=409, detail="No pending stage on this chain")
    earlier_pending = [s for s in steps if s.sequence < current.sequence and s.decision != ApprovalDecision.APPROVED]
    if earlier_pending:
        raise HTTPException(
            status_code=409,
            detail=f"Stage {current.stage.value} cannot be decided until {earlier_pending[0].stage.value} is approved",
        )

    current.decision = payload.decision
    current.decided_by = actor.id
    current.decided_at = datetime.now(timezone.utc)
    current.note = payload.note
    session.flush()

    if payload.decision == ApprovalDecision.REJECTED:
        chain.final_decision = ApprovalDecision.REJECTED
        chain.completed_at = datetime.now(timezone.utc)
    elif current.sequence == len(STAGE_ORDER) - 1:
        chain.final_decision = ApprovalDecision.APPROVED
        chain.completed_at = datetime.now(timezone.utc)
    session.flush()

    AuditLedger(session).append(
        action="APPROVAL_STAGE_DECIDED", entity_type="approval_step", entity_id=str(current.id),
        actor_id=str(actor.id),
        payload={"chain_id": str(chain.id), "stage": current.stage.value, "decision": payload.decision.value},
    )
    return _out(session, chain)


def _aware(dt: datetime) -> datetime:
    """SQLite silently drops tzinfo even on a DateTime(timezone=True)
    column; PostgreSQL does not. Normalise defensively so this code works
    identically on both, rather than assuming one database's behaviour."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _out(session: Session, chain: ApprovalChain) -> dict:
    steps = sorted(chain.steps, key=lambda s: s.sequence)
    current = next((s for s in steps if s.decision == ApprovalDecision.PENDING), None)
    capa = session.get(CapaItem, chain.capa_id)
    return {
        "chain_id": str(chain.id), "capa_id": str(chain.capa_id),
        "mine_id": str(capa.mine_id) if capa else None,
        "reason": chain.reason, "final_decision": chain.final_decision.value,
        "current_stage": current.stage.value if current else None,
        "completed_at": chain.completed_at.isoformat() if chain.completed_at else None,
        "created_at": chain.created_at.isoformat(),
        "steps": [
            {"stage": s.stage.value, "decision": s.decision.value,
            "decided_at": s.decided_at.isoformat() if s.decided_at else None,
            "note": s.note,
            "waiting_hours": round((datetime.now(timezone.utc) - _aware(chain.created_at)).total_seconds() / 3600, 1)
                            if s.decision == ApprovalDecision.PENDING else None}
            for s in steps
        ],
    }

"""M0 - statutory rule registry and mine obligations."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import assert_mine_access, get_current_user, require_any
from models.enums import ObligationStatus
from models.identity import User
from models.statutory import MineObligation, StatutoryRule
from schemas.domain import ObligationOut, StatutoryRuleCreate, StatutoryRuleOut
from services import obligations as obligation_service
from services import rbac
from services.audit import AuditLedger

router = APIRouter(tags=["M0 statutory"])


@router.get("/statutory/rules", response_model=list[StatutoryRuleOut])
def list_rules(
    active_only: bool = True,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(StatutoryRule).order_by(StatutoryRule.rule_code)
    if active_only:
        stmt = stmt.where(StatutoryRule.is_active.is_(True))
    return list(session.execute(stmt).scalars())


@router.get("/compliance-copilot")
def compliance_copilot(
    question: str, mine_id: uuid.UUID | None = None,
    session: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Deterministic grounded retrieval over the real M0 corpus - see
    services/compliance_copilot.py's module docstring for exactly why
    this is not, and does not pretend to be, an LLM."""
    from services.compliance_copilot import answer_question

    if mine_id is not None:
        assert_mine_access(session, user, mine_id)
    return answer_question(session, question, mine_id)


@router.get("/statutory/registry-status")
def registry_status(
    session: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """How much of the statute is actually loaded.

    Stated explicitly so the prototype is never mistaken for a complete
    statutory corpus, and so unverified clause references are visible.
    """
    rules = list(session.execute(select(StatutoryRule)).scalars())
    unverified = [r for r in rules if r.clause_verification.value == "UNVERIFIED"]
    return {
        "rules_loaded": len(rules),
        "clause_references_unverified": len(unverified),
        "is_complete_statutory_corpus": False,
        "note": (
            "High-frequency obligations are seeded as a proof of concept. "
            "The full statutory corpus is deployment scope. Clause "
            "references marked UNVERIFIED have not been checked against the "
            "published statute and must not be presented as authoritative."
        ),
    }


@router.post("/statutory/rules", response_model=StatutoryRuleOut, status_code=201)
def create_rule(
    payload: StatutoryRuleCreate,
    session: Session = Depends(get_db),
    actor: User = Depends(require_any(rbac.RULE_EDITORS)),
):
    if session.execute(
        select(StatutoryRule).where(StatutoryRule.rule_code == payload.rule_code)
    ).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="rule_code already exists")
    rule = StatutoryRule(**payload.model_dump())
    session.add(rule)
    session.flush()
    AuditLedger(session).append(
        action="STATUTORY_RULE_CREATED", entity_type="statutory_rule",
        entity_id=str(rule.id), actor_id=str(actor.id),
        payload={"rule_code": rule.rule_code, "clause": rule.clause},
    )
    return rule


@router.get("/mines/{mine_id}/obligations", response_model=list[ObligationOut])
def list_obligations(
    mine_id: uuid.UUID,
    status_filter: ObligationStatus | None = Query(default=None, alias="status"),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    assert_mine_access(session, user, mine_id)
    stmt = select(MineObligation).where(MineObligation.mine_id == mine_id)
    if status_filter:
        stmt = stmt.where(MineObligation.status == status_filter)
    return list(session.execute(stmt).scalars())


@router.post("/mines/{mine_id}/obligations/sync", response_model=list[ObligationOut])
def sync_obligations(
    mine_id: uuid.UUID,
    session: Session = Depends(get_db),
    actor: User = Depends(require_any(rbac.VERIFIERS | rbac.RULE_EDITORS)),
):
    """Materialise every applicable rule as an obligation for this mine.

    Obligations are created whether or not any document exists. That is
    what makes MISSING detectable: an obligation that should have been met
    and never was, rather than only a document that expired.
    """
    mine = assert_mine_access(session, actor, mine_id)
    created = obligation_service.sync_obligations_for_mine(session, mine)
    AuditLedger(session).append(
        action="OBLIGATIONS_SYNCED", entity_type="mine", entity_id=str(mine.id),
        actor_id=str(actor.id), payload={"created": len(created)},
    )
    return list(session.execute(
        select(MineObligation).where(MineObligation.mine_id == mine_id)
    ).scalars())


@router.post("/mines/{mine_id}/obligations/refresh")
def refresh_obligations(
    mine_id: uuid.UUID,
    session: Session = Depends(get_db),
    actor: User = Depends(require_any(rbac.VERIFIERS | rbac.RULE_EDITORS)),
):
    """Recompute every obligation status against the documents on file."""
    assert_mine_access(session, actor, mine_id)
    items = list(session.execute(
        select(MineObligation).where(MineObligation.mine_id == mine_id)
    ).scalars())
    today = date.today()
    counts: dict[str, int] = {}
    for obligation in items:
        assessment = obligation_service.refresh_status(session, obligation, today)
        counts[assessment.status.value] = counts.get(assessment.status.value, 0) + 1
    return {"evaluated": len(items), "by_status": counts, "as_of": today.isoformat()}

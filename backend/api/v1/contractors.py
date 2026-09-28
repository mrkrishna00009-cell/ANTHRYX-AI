"""Contractor Passport.

Uses the existing Contractor / ContractorSite schema exactly as it was
designed in Phase 2 - no new tables. Cross-site compliance visibility:
a contractor's violation history is read from the existing
Document.contractor_id linkage (a contractor's own certificates/permits)
and from CapaItem rows raised at a mine while that contractor held an
active ContractorSite there, which is the only honest, defensible way to
attribute a "contractor violation" without a dedicated
contractor_violations table this project does not have.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from models.capa import CapaItem
from models.documents import Contractor, ContractorSite, Document
from models.enums import CapaStatus
from models.identity import User
from models.organisation import Mine

router = APIRouter(tags=["contractor passport"])


@router.get("/contractors")
def list_contractors(session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    contractors = session.execute(select(Contractor).order_by(Contractor.name)).scalars().all()
    result = []
    for c in contractors:
        sites = session.execute(
            select(ContractorSite).where(ContractorSite.contractor_id == c.id)
        ).scalars().all()
        result.append({
            "contractor_id": str(c.id), "code": c.code, "name": c.name, "trade": c.trade,
            "status": c.status.value, "active_site_count": sum(1 for s in sites if s.is_active),
            "total_site_count": len(sites),
        })
    return result


@router.get("/contractors/{contractor_id}")
def contractor_passport(
    contractor_id: uuid.UUID, session: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Cross-site view: every mine this contractor is or was engaged at,
    and every CAPA raised at those mines during an active engagement
    window - the honest, schema-supported definition of a "contractor
    violation" this project can actually compute."""
    contractor = session.get(Contractor, contractor_id)
    if contractor is None:
        raise HTTPException(status_code=404, detail="Contractor not found")

    sites = session.execute(
        select(ContractorSite).where(ContractorSite.contractor_id == contractor_id)
    ).scalars().all()

    site_rows = []
    cross_site_warning = None
    active_mine_ids = {s.mine_id for s in sites if s.is_active}
    debarred_elsewhere = contractor.status == "DEBARRED" if isinstance(contractor.status, str) else contractor.status.value == "DEBARRED"

    for s in sites:
        mine = session.get(Mine, s.mine_id)
        capas_at_mine = session.execute(
            select(CapaItem).where(CapaItem.mine_id == s.mine_id)
        ).scalars().all()
        # Attribute a CAPA to this contractor only if it was raised while
        # the engagement window covers its creation date - never a blanket
        # "every CAPA at this mine ever" claim.
        relevant = [
            c for c in capas_at_mine
            if (s.contract_start is None or c.created_at.date() >= s.contract_start)
            and (s.contract_end is None or c.created_at.date() <= s.contract_end)
        ]
        site_rows.append({
            "mine_id": str(s.mine_id), "mine_name": mine.name if mine else "(unknown)",
            "is_active": s.is_active, "contract_start": s.contract_start.isoformat() if s.contract_start else None,
            "contract_end": s.contract_end.isoformat() if s.contract_end else None,
            "capa_count_during_engagement": len(relevant),
            "open_capa_count_during_engagement": sum(1 for c in relevant if c.status != CapaStatus.CLOSED),
        })

    if contractor.status.value == "DEBARRED" and active_mine_ids:
        cross_site_warning = (
            f"This contractor is DEBARRED but holds {len(active_mine_ids)} active site "
            f"engagement(s) - local debarment status has not propagated across all sites."
        )

    documents = session.execute(
        select(Document).where(Document.contractor_id == contractor_id)
    ).scalars().all()

    return {
        "contractor_id": str(contractor.id), "code": contractor.code, "name": contractor.name,
        "trade": contractor.trade, "status": contractor.status.value,
        "registered_on": contractor.registered_on.isoformat() if contractor.registered_on else None,
        "sites": site_rows,
        "document_count": len(documents),
        "cross_site_warning": cross_site_warning,
        "note": (
            "CAPA attribution is engagement-window-based (a CAPA raised at a mine while this "
            "contractor's contract dates covered it) - this project has no dedicated "
            "contractor_violations table, so this is the most defensible mapping available."
        ),
    }

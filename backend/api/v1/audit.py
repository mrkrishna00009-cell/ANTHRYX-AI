"""M6 - tamper-evident audit ledger and statutory reporting status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_any
from datetime import date

import uuid

from models.enums import Role
from models.identity import User
from schemas.common import NotImplementedNotice
from schemas.domain import AuditEntryOut, ChainVerificationOut
from services.audit import AuditLedger

router = APIRouter(tags=["M6 audit and reporting"])

AUDIT_READERS = frozenset(
    {Role.ADMIN, Role.DGMS_REGULATOR, Role.SUBSIDIARY_HEAD, Role.MINE_MANAGER}
)


@router.get("/audit", response_model=list[AuditEntryOut])
def list_entries(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
    user: User = Depends(require_any(AUDIT_READERS)),
):
    return AuditLedger(session).entries(limit=limit, offset=offset)


@router.get("/audit/verify", response_model=ChainVerificationOut)
def verify(
    session: Session = Depends(get_db),
    user: User = Depends(require_any(AUDIT_READERS)),
):
    """Walk the whole chain and report intact, or the sequence that breaks."""
    return ChainVerificationOut(**AuditLedger(session).verify().as_dict())


@router.post("/audit/tamper-drill")
def tamper_drill(
    target_seq: int = Query(description="Sequence number to corrupt in the copy"),
    session: Session = Depends(get_db),
    user: User = Depends(require_any({Role.ADMIN, Role.DGMS_REGULATOR})),
):
    """Demonstrate detection without damaging the stored ledger.

    The chain is copied into memory, the copy is altered, and the copy is
    verified. Nothing is written, so the demonstration can be repeated.
    """
    return AuditLedger(session).tamper_drill(target_seq)


@router.get("/audit/properties")
def properties(user: User = Depends(get_current_user)):
    return {
        "property": "tamper-evident",
        "is_immutable": False,
        "is_blockchain": False,
        "hash_formula": (
            "SHA256(seq | actor_id | action | entity_type | entity_id | "
            "timestamp | payload_json | prev_hash)"
        ),
        "seq_inside_hash": True,
        "detects": [
            "edit to any interior row",
            "deletion of any interior row",
            "renumbering of a sequence",
        ],
        "does_not_detect": [
            "truncation of the newest rows without an external anchor",
        ],
        "note": (
            "Hash chaining gives the tamper-evidence property without the "
            "cost of distributed consensus. It detects retroactive edits; it "
            "does not prevent them, and it is not a blockchain."
        ),
    }


@router.get("/reports/status")
def report_status(user: User = Depends(get_current_user)):
    return {
        "generator_implemented": True,
        "phase_implemented": "Phase 4",
        "output_label": "REPRESENTATIVE_STATUTORY_RETURN",
        "official_format_verified": False,
        "note": (
            "Until the official Form IV layout has been checked against the "
            "published form, generated output is labelled a representative "
            "statutory return. Claiming official-form compliance without "
            "that check would be false."
        ),
    }


@router.post("/reports/generate")
def generate(
    mine_id: uuid.UUID,
    period_start: date | None = None,
    period_end: date | None = None,
    session: Session = Depends(get_db),
    actor: User = Depends(require_any(AUDIT_READERS)),
):
    """Generates a REPRESENTATIVE_STATUTORY_RETURN PDF from real data.
    Never claims official Form IV compliance - that layout has not been
    verified against the published form."""
    import base64
    from models.reporting import Report
    from models.enums import ReportKind
    from services.reports import generate_compliance_report

    try:
        pdf_bytes, payload = generate_compliance_report(session, mine_id, period_start, period_end)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    report = Report(
        mine_id=mine_id, kind=ReportKind.REPRESENTATIVE_STATUTORY_RETURN,
        period_start=period_start, period_end=period_end,
        file_hash=payload["file_hash"], official_format_verified=False,
        generated_by=actor.id, payload=payload,
    )
    session.add(report)
    session.flush()

    AuditLedger(session).append(
        action="REPORT_GENERATED", entity_type="report", entity_id=str(report.id),
        actor_id=str(actor.id), payload=payload,
    )
    return {
        "report_id": str(report.id),
        "kind": report.kind.value,
        "official_format_verified": False,
        "file_hash": payload["file_hash"],
        "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        "summary": payload,
    }

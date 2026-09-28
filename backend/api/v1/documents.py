"""M1 - document lifecycle and the human verification queue.

OCR extraction is never compliance verification. A document satisfies an
obligation only after a person has verified it, which is why the
verification queue is a separate governed workflow rather than a checkbox.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import assert_mine_access, get_current_user, require_any
from models.documents import Document, ExtractedField
from models.enums import OcrEngine, VerificationStatus
from models.identity import User
from models.statutory import MineObligation
from schemas.common import NotImplementedNotice
from schemas.domain import DocumentCreate, DocumentOut, DocumentVerify
from services import obligations as obligation_service
from services import rbac
from services.audit import AuditLedger
from integrations.factory import select_language_provider

router = APIRouter(tags=["M1 documents"])


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    mine_id: uuid.UUID | None = None,
    status_filter: VerificationStatus | None = Query(default=None, alias="status"),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Document).order_by(Document.created_at.desc())
    if mine_id:
        assert_mine_access(session, user, mine_id)
        stmt = stmt.where(Document.mine_id == mine_id)
    if status_filter:
        stmt = stmt.where(Document.verification_status == status_filter)
    return list(session.execute(stmt).scalars())


@router.get("/documents/verification-queue", response_model=list[DocumentOut])
def verification_queue(
    session: Session = Depends(get_db),
    user: User = Depends(require_any(rbac.VERIFIERS)),
):
    """Everything awaiting a human decision, lowest confidence first."""
    return list(session.execute(
        select(Document)
        .where(Document.verification_status == VerificationStatus.PENDING_VERIFICATION)
        .order_by(Document.ocr_confidence.asc().nulls_first())
    ).scalars())


@router.post("/documents", response_model=DocumentOut, status_code=201)
def create_document(
    payload: DocumentCreate,
    session: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    assert_mine_access(session, actor, payload.mine_id)
    document = Document(
        **payload.model_dump(),
        uploaded_by=actor.id,
        uploaded_at=datetime.now(timezone.utc),
        verification_status=VerificationStatus.PENDING_VERIFICATION,
    )
    session.add(document)
    session.flush()
    AuditLedger(session).append(
        action="DOCUMENT_UPLOADED", entity_type="document",
        entity_id=str(document.id), actor_id=str(actor.id),
        payload={"doc_type": document.doc_type, "mine_id": str(document.mine_id)},
    )
    return document


@router.post("/documents/{document_id}/verify", response_model=DocumentOut)
def verify_document(
    document_id: uuid.UUID,
    payload: DocumentVerify,
    session: Session = Depends(get_db),
    actor: User = Depends(require_any(rbac.VERIFIERS)),
):
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    assert_mine_access(session, actor, document.mine_id)
    if document.verification_status is not VerificationStatus.PENDING_VERIFICATION:
        raise HTTPException(
            status_code=409,
            detail=f"Document is already {document.verification_status.value}",
        )

    document.verification_status = payload.decision
    document.verified_by = actor.id
    document.verified_at = datetime.now(timezone.utc)
    if payload.decision is VerificationStatus.REJECTED:
        document.rejection_reason = payload.note

    # Record which extracted values the officer had to correct. This is the
    # honest measure of how often OCR was wrong.
    for name, corrected in (payload.corrected_fields or {}).items():
        field = session.execute(
            select(ExtractedField).where(
                ExtractedField.document_id == document.id,
                ExtractedField.field_name == name,
            )
        ).scalar_one_or_none()
        if field is None:
            field = ExtractedField(document_id=document.id, field_name=name)
            session.add(field)
        field.was_corrected = (field.raw_value or "") != corrected
        field.confirmed_value = corrected

    session.flush()

    # A verified document can now satisfy its obligation.
    if (
        payload.decision is VerificationStatus.VERIFIED
        and document.rule_id is not None
    ):
        obligation = session.execute(
            select(MineObligation).where(
                MineObligation.mine_id == document.mine_id,
                MineObligation.rule_id == document.rule_id,
            )
        ).scalar_one_or_none()
        if obligation is not None:
            obligation_service.refresh_status(session, obligation)

    AuditLedger(session).append(
        action="DOCUMENT_VERIFIED" if payload.decision is VerificationStatus.VERIFIED
        else "DOCUMENT_REJECTED",
        entity_type="document", entity_id=str(document.id), actor_id=str(actor.id),
        payload={
            "decision": payload.decision.value,
            "corrected_fields": sorted((payload.corrected_fields or {}).keys()),
        },
    )
    return document


@router.get("/documents/ocr/status")
def ocr_status(user: User = Depends(get_current_user)):
    """What the OCR chain would actually do right now."""
    settings = get_settings()
    selection = select_language_provider(settings)
    return {
        "primary_engine": "TESSERACT",
        "fallback_provider": selection.as_dict(),
        "confidence_threshold": settings.ocr_confidence_threshold,
        "policy": (
            "Tesseract runs first. Only if its mean confidence falls below "
            "the threshold, or a non-Latin script is detected, is the "
            "fallback provider called."
        ),
        "extraction_pipeline_implemented": True,
        "phase_implemented": "Phase 4",
    }


@router.post("/documents/{document_id}/extract")
async def extract(
    document_id: uuid.UUID,
    file: UploadFile,
    session: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """The locked OCR pipeline: Tesseract primary, confidence-gated
    Bhashini/demo fallback. Stores the file hash on the Document (so a
    later substitution is detectable) and one ExtractedField per run
    (``field_name='raw_text'``) rather than inventing a per-doc-type
    structured schema this project has not specified. was_corrected is
    populated later, at verification time, exactly as before."""
    import hashlib

    from services.ocr import run_ocr
    from services.uploads import read_validated_upload

    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    assert_mine_access(session, actor, document.mine_id)

    settings = get_settings()
    image_bytes = await read_validated_upload(
        file, max_bytes=settings.max_document_upload_bytes,
        allowed_content_types=settings.allowed_document_content_types,
    )
    result = run_ocr(image_bytes)

    ENGINE_MAP = {
        "TESSERACT": OcrEngine.TESSERACT,
        "bhashini": OcrEngine.BHASHINI,
        "demo-fallback": OcrEngine.DEMO_FALLBACK,
    }
    document.file_hash = hashlib.sha256(image_bytes).hexdigest()
    document.ocr_engine = ENGINE_MAP.get(result.engine, OcrEngine.NONE)
    document.ocr_confidence = result.confidence

    field = ExtractedField(
        document_id=document.id, field_name="raw_text",
        raw_value=result.text or None, confidence=result.confidence,
        ocr_engine=document.ocr_engine,
    )
    session.add(field)
    session.flush()

    AuditLedger(session).append(
        action="DOCUMENT_OCR_EXTRACTED", entity_type="document",
        entity_id=str(document.id), actor_id=str(actor.id),
        payload={
            "engine": result.engine, "status": result.status.value,
            "confidence": result.confidence, "file_hash": document.file_hash,
        },
    )
    return {
        "document_id": str(document.id),
        "engine": result.engine, "provider_status": result.status.value,
        "confidence": result.confidence,
        "extracted_text": result.text,
        "detail": result.detail,
        "verification_required": True,
        "policy": "OCR extraction is never compliance verification; a human must verify.",
    }

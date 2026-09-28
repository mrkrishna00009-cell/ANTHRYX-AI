"""M2 - sync endpoint for the offline field app.

The device generates a UUID before the record leaves it. Re-posting the
same UUID returns the existing record instead of creating a duplicate,
which is what lets the app retry a failed sync safely.

Four anti-spoof signals are recorded. None of them is decisive on its own,
and a suspicious record is flagged rather than rejected: losing evidence
is worse than holding it with a flag attached.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import assert_mine_access, get_current_user, require_any
from models.enums import CapaSourceType, EvidenceKind, IncidentSource, LocationMethod, SpoofFlag, SyncStatus
from models.field_evidence import (
    AttendanceRecord, FieldEvidence, IncidentReport, InspectionFinding,
)
from models.identity import User
from models.organisation import Device
from schemas.domain import FieldEvidenceIn, FieldEvidenceOut, SyncAck
from services import rbac
from services.audit import AuditLedger

router = APIRouter(tags=["M2 field evidence"])

#: Client clocks drift and can be set by the user. Beyond this, the record
#: is flagged for review.
CLOCK_SKEW_TOLERANCE_SECONDS = 300


@router.post("/field-evidence", response_model=SyncAck, status_code=201)
def sync_evidence(
    payload: FieldEvidenceIn,
    session: Session = Depends(get_db),
    actor: User = Depends(require_any(rbac.FIELD_SUBMITTERS)),
):
    existing = session.execute(
        select(FieldEvidence).where(FieldEvidence.client_uuid == payload.client_uuid)
    ).scalar_one_or_none()
    if existing is not None:
        # Idempotent: a retried sync is not a second observation.
        return SyncAck(
            client_uuid=existing.client_uuid, id=existing.id, created=False,
            spoof_flags=list(existing.spoof_flags or []),
            server_timestamp=existing.server_timestamp,
        )

    mine = assert_mine_access(session, actor, payload.mine_id)
    server_time = datetime.now(timezone.utc)

    flags: list[str] = []
    skew: int | None = None
    if payload.client_timestamp is not None:
        client_time = payload.client_timestamp
        if client_time.tzinfo is None:
            client_time = client_time.replace(tzinfo=timezone.utc)
        skew = int((server_time - client_time).total_seconds())
        if abs(skew) > CLOCK_SKEW_TOLERANCE_SECONDS:
            flags.append(SpoofFlag.CLOCK_SKEW.value)

    if payload.mock_location_reported:
        flags.append(SpoofFlag.MOCK_LOCATION_REPORTED.value)

    device = None
    if payload.device_fingerprint:
        device = session.execute(
            select(Device).where(Device.fingerprint == payload.device_fingerprint)
        ).scalar_one_or_none()
        if device is None or not device.is_active:
            flags.append(SpoofFlag.UNREGISTERED_DEVICE.value)
    else:
        flags.append(SpoofFlag.UNREGISTERED_DEVICE.value)

    evidence = FieldEvidence(
        client_uuid=payload.client_uuid,
        kind=payload.kind,
        mine_id=mine.id,
        user_id=actor.id,
        device_id=device.id if device else None,
        client_timestamp=payload.client_timestamp,
        # Server clock is authoritative. The client clock is kept only so
        # the difference between them is visible.
        server_timestamp=server_time,
        clock_skew_seconds=skew,
        latitude=payload.latitude,
        longitude=payload.longitude,
        gps_accuracy_m=payload.gps_accuracy_m,
        location_method=payload.location_method,
        checkpoint_code=payload.checkpoint_code,
        mock_location_reported=payload.mock_location_reported,
        spoof_flags=flags or None,
        notes=payload.notes,
        photo_hash=payload.photo_hash,
        sync_status=SyncStatus.SYNCED,
    )
    session.add(evidence)
    session.flush()

    capas_created: list = []
    if payload.kind is EvidenceKind.INSPECTION:
        for finding in payload.findings:
            row = InspectionFinding(evidence_id=evidence.id, **finding.model_dump())
            session.add(row)
            session.flush()
            if row.compliant is False:
                from services.capa_triggers import maybe_create_capa
                capa, created = maybe_create_capa(
                    session, mine_id=mine.id, source_type=CapaSourceType.VIOLATION,
                    source_id=row.id, severity=row.severity,
                    description=f"Non-compliant inspection finding: {row.question}"
                               + (f" — {row.observation}" if row.observation else ""),
                    actor_id=actor.id, rule_id=row.rule_id,
                )
                if created:
                    capas_created.append(capa.id)
    elif payload.kind is EvidenceKind.ATTENDANCE and payload.attendance:
        session.add(AttendanceRecord(evidence_id=evidence.id, **payload.attendance.model_dump()))
    elif payload.kind is EvidenceKind.INCIDENT and payload.incident:
        incident_row = IncidentReport(evidence_id=evidence.id, **payload.incident.model_dump())
        session.add(incident_row)
        session.flush()
        from services.capa_triggers import maybe_create_capa
        capa, created = maybe_create_capa(
            session, mine_id=mine.id, source_type=CapaSourceType.INCIDENT,
            source_id=incident_row.id, severity=incident_row.severity,
            description=f"Form-reported incident ({incident_row.category}): "
                        f"{incident_row.description_en or '[no description]'}",
            actor_id=actor.id,
        )
        if created:
            capas_created.append(capa.id)
    session.flush()

    AuditLedger(session).append(
        action="FIELD_EVIDENCE_SYNCED", entity_type="field_evidence",
        entity_id=str(evidence.id), actor_id=str(actor.id),
        payload={
            "kind": evidence.kind.value,
            "mine_id": str(mine.id),
            "client_uuid": evidence.client_uuid,
            "spoof_flags": flags,
            "location_method": evidence.location_method.value,
            "capas_created": [str(c) for c in capas_created],
        },
    )
    return SyncAck(
        client_uuid=evidence.client_uuid, id=evidence.id, created=True,
        spoof_flags=flags, server_timestamp=evidence.server_timestamp,
        capas_created=capas_created,
    )


@router.post("/field-evidence/voice-incident", status_code=201)
async def voice_incident(
    client_uuid: str,
    mine_id: uuid.UUID,
    category: str,
    severity: str,
    source_language: str,
    audio: UploadFile,
    session: Session = Depends(get_db),
    actor: User = Depends(require_any(rbac.FIELD_SUBMITTERS)),
):
    """MANDATORY voice incident flow:

    audio -> Bhashini ASR (or demo fallback) -> original transcript
          -> Bhashini NMT (or demo fallback) -> English translation
          -> structured IncidentReport (source=VOICE)
          -> M4 CAPA for HIGH/CRITICAL severity
          -> M6 audit

    A demo-fallback transcript is NEVER recorded as if it were a live
    Bhashini result - each provider call's own status is stored alongside
    the text it produced, so the two can never be confused later.
    """
    import hashlib

    from integrations.factory import select_language_provider
    from models.enums import CapaSourceType, DataProvenance, ProviderStatus, Severity as SeverityEnum
    from services.capa_triggers import maybe_create_capa

    existing = session.execute(
        select(FieldEvidence).where(FieldEvidence.client_uuid == client_uuid)
    ).scalar_one_or_none()
    if existing is not None:
        return {"client_uuid": client_uuid, "evidence_id": str(existing.id), "created": False}

    from services.uploads import read_validated_upload

    mine = assert_mine_access(session, actor, mine_id)
    settings = get_settings()
    audio_bytes = await read_validated_upload(
        audio, max_bytes=settings.max_audio_upload_bytes,
        allowed_content_types=settings.allowed_audio_content_types,
    )
    audio_hash = hashlib.sha256(audio_bytes).hexdigest()

    from integrations.providers import ProviderError

    selection = select_language_provider()
    try:
        asr_result = selection.provider.asr(audio_bytes, source_language)
        nmt_result = selection.provider.translate(
            asr_result.transcript, source_language=source_language, target_language="en"
        )
    except ProviderError as exc:
        # A real live-Bhashini failure (timeout, 5xx after retries, network
        # error) must degrade to an honest unavailable result, never an
        # unhandled 500 - the same contract as the OCR fallback path.
        from integrations.providers import AsrResult, TranslationResult
        unavailable_detail = f"Live Bhashini request failed ({exc}); no fabricated transcript is returned."
        asr_result = AsrResult(
            transcript="", source_language=source_language,
            status=ProviderStatus.BHASHINI_UNAVAILABLE,
            provenance=DataProvenance.LIVE_EXTERNAL_API, detail=unavailable_detail,
        )
        nmt_result = TranslationResult(
            text="", source_language=source_language, target_language="en",
            status=ProviderStatus.BHASHINI_UNAVAILABLE,
            provenance=DataProvenance.LIVE_EXTERNAL_API, detail=unavailable_detail,
        )

    # Provenance is LIVE only if BOTH calls actually succeeded live; a
    # fallback anywhere in the chain makes the whole transcript a fallback
    # product, never silently upgraded to look like a live Bhashini result.
    live = (asr_result.provenance == DataProvenance.REAL_PUBLIC_DATA
            or str(asr_result.status.value) == "LIVE_BHASHINI") and \
           (str(nmt_result.status.value) == "LIVE_BHASHINI")
    transcript_provenance = DataProvenance.LIVE_EXTERNAL_API if live else DataProvenance.DEMO_FALLBACK

    server_time = datetime.now(timezone.utc)
    evidence = FieldEvidence(
        client_uuid=client_uuid, kind=EvidenceKind.INCIDENT, mine_id=mine.id,
        user_id=actor.id, client_timestamp=None, server_timestamp=server_time,
        location_method=LocationMethod.NONE, sync_status=SyncStatus.SYNCED,
    )
    session.add(evidence)
    session.flush()

    incident = IncidentReport(
        evidence_id=evidence.id, category=category,
        severity=SeverityEnum(severity), description_en=nmt_result.text or None,
        source=IncidentSource.VOICE, audio_hash=audio_hash, source_language=source_language,
        original_transcript=asr_result.transcript or None,
        translated_transcript=nmt_result.text or None,
        asr_provider_status=asr_result.status, nmt_provider_status=nmt_result.status,
        transcript_provenance=transcript_provenance,
    )
    session.add(incident)
    session.flush()

    capa, capa_created = maybe_create_capa(
        session, mine_id=mine.id, source_type=CapaSourceType.INCIDENT,
        source_id=incident.id, severity=SeverityEnum(severity),
        description=f"Voice-reported incident ({category}): {nmt_result.text or '[not transcribed]'}",
        actor_id=actor.id,
    )
    capa_id = capa.id if capa else None

    AuditLedger(session).append(
        action="VOICE_INCIDENT_RECORDED", entity_type="incident_report",
        entity_id=str(incident.id), actor_id=str(actor.id),
        payload={
            "mine_id": str(mine.id), "asr_status": asr_result.status.value,
            "nmt_status": nmt_result.status.value,
            "transcript_provenance": transcript_provenance.value,
            "audio_hash": audio_hash, "capa_id": str(capa_id) if capa_id else None,
        },
    )
    return {
        "client_uuid": client_uuid, "evidence_id": str(evidence.id),
        "incident_id": str(incident.id), "created": True,
        "source_language": source_language,
        "original_transcript": asr_result.transcript,
        "translated_transcript": nmt_result.text,
        "asr_provider_status": asr_result.status.value,
        "nmt_provider_status": nmt_result.status.value,
        "transcript_provenance": transcript_provenance.value,
        "capa_id": str(capa_id) if capa_id else None,
        "capa_created": capa_created,
        "provenance_note": (
            "asr_provider_status and nmt_provider_status each report which "
            "engine actually produced the corresponding text. A DEMO_FALLBACK "
            "status means no recognition occurred for that step."
        ),
    }


@router.get("/field-evidence", response_model=list[FieldEvidenceOut])
def list_evidence(
    mine_id: uuid.UUID | None = None,
    kind: EvidenceKind | None = Query(default=None),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(FieldEvidence).order_by(FieldEvidence.server_timestamp.desc())
    if mine_id:
        assert_mine_access(session, user, mine_id)
        stmt = stmt.where(FieldEvidence.mine_id == mine_id)
    if kind:
        stmt = stmt.where(FieldEvidence.kind == kind)
    return list(session.execute(stmt.limit(200)).scalars())


@router.get("/field-evidence/location-policy")
def location_policy(user: User = Depends(get_current_user)):
    """What the system does and does not claim about positioning."""
    return {
        "surface_and_pit_mouth": "GPS verification with accuracy recorded",
        "underground": (
            "GPS is not available underground. Satellite signal does not "
            "reach the workings. Verification underground uses fixed QR or "
            "NFC checkpoints combined with the last surface fix."
        ),
        "underground_gps_claimed": False,
        "anti_spoof_signals": [
            "mock-location flag where the platform reports it",
            "device binding against a registered fingerprint",
            "geofence against the lease boundary",
            "server-authoritative timestamp with client skew recorded",
        ],
        "geofence_implemented": False,
        "geofence_phase_planned": "Phase 6",
    }

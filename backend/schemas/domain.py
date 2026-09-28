"""Request/response schemas for the domain modules."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from models.enums import (
    CapaSourceType, CapaStatus, ClauseVerification, DataProvenance,
    EvidenceKind, IncidentSource, LocationMethod, MineStatus, MineType,
    ObligationStatus, ObligationType, SensorKind, Severity, VerificationStatus,
)
from schemas.common import ORMModel


# --- organisation ------------------------------------------------------
class SubsidiaryOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    state: str | None = None


class MineOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    mine_type: MineType
    status: MineStatus
    district: str | None = None
    state: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    coordinate_is_approximate: bool
    coordinate_provenance: DataProvenance
    coordinate_note: str | None = None
    subsidiary_id: uuid.UUID | None = None


class MineCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    mine_type: MineType
    district: str | None = None
    state: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    # Defaults to approximate. A caller must assert otherwise deliberately.
    coordinate_is_approximate: bool = True
    coordinate_note: str | None = None
    subsidiary_id: uuid.UUID | None = None


# --- M0 ----------------------------------------------------------------
class StatutoryRuleOut(ORMModel):
    id: uuid.UUID
    rule_code: str
    statute: str
    clause: str
    title: str
    obligation_type: ObligationType
    frequency_days: int | None = None
    applies_to_underground: bool
    applies_to_opencast: bool
    severity: Severity
    evidence_required: str | None = None
    authority: str
    clause_verification: ClauseVerification
    is_active: bool


class StatutoryRuleCreate(BaseModel):
    rule_code: str = Field(min_length=1, max_length=48)
    statute: str = Field(min_length=1, max_length=160)
    clause: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=300)
    obligation_type: ObligationType
    frequency_days: int | None = Field(default=None, ge=1, le=3650)
    applies_to_underground: bool = True
    applies_to_opencast: bool = True
    severity: Severity
    evidence_required: str | None = None
    authority: str = "DGMS"
    # Seeded clause references start unverified and must be checked against
    # the statute before being presented as authoritative.
    clause_verification: ClauseVerification = ClauseVerification.UNVERIFIED
    source_reference: str | None = None


class ObligationOut(ORMModel):
    id: uuid.UUID
    mine_id: uuid.UUID
    rule_id: uuid.UUID
    last_satisfied_date: date | None = None
    next_due_date: date | None = None
    status: ObligationStatus
    note: str | None = None


# --- M1 ----------------------------------------------------------------
class DocumentOut(ORMModel):
    id: uuid.UUID
    mine_id: uuid.UUID
    rule_id: uuid.UUID | None = None
    contractor_id: uuid.UUID | None = None
    doc_type: str
    certificate_no: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    file_hash: str | None = None
    ocr_confidence: float | None = None
    verification_status: VerificationStatus
    verified_at: datetime | None = None


class DocumentCreate(BaseModel):
    mine_id: uuid.UUID
    rule_id: uuid.UUID | None = None
    contractor_id: uuid.UUID | None = None
    doc_type: str = Field(min_length=1, max_length=120)
    certificate_no: str | None = Field(default=None, max_length=160)
    issue_date: date | None = None
    expiry_date: date | None = None

    @field_validator("expiry_date")
    @classmethod
    def expiry_after_issue(cls, v, info):
        issue = info.data.get("issue_date")
        if v and issue and v < issue:
            raise ValueError("expiry_date cannot precede issue_date")
        return v


class DocumentVerify(BaseModel):
    decision: VerificationStatus
    note: str | None = None
    corrected_fields: dict[str, str] | None = None

    @field_validator("decision")
    @classmethod
    def only_terminal_decisions(cls, v):
        if v is VerificationStatus.PENDING_VERIFICATION:
            raise ValueError("decision must be VERIFIED or REJECTED")
        return v


# --- M2 ----------------------------------------------------------------
class InspectionFindingIn(BaseModel):
    rule_id: uuid.UUID | None = None
    question: str = Field(min_length=1)
    compliant: bool | None = None
    severity: Severity | None = None
    observation: str | None = None


class AttendanceIn(BaseModel):
    worker_code: str = Field(min_length=1, max_length=64)
    contractor_id: uuid.UUID | None = None
    shift: str | None = None
    checked_in: bool = True


class IncidentIn(BaseModel):
    category: str = Field(min_length=1, max_length=120)
    severity: Severity
    description_en: str | None = None
    source: IncidentSource = IncidentSource.FORM
    source_language: str | None = None
    original_transcript: str | None = None


class FieldEvidenceIn(BaseModel):
    """A record synced from the offline field app.

    ``client_uuid`` is generated on the device before the record leaves it,
    which is what makes a retried sync idempotent rather than duplicating.
    ``client_timestamp`` is recorded but is never authoritative.
    """

    client_uuid: str = Field(min_length=8, max_length=64)
    kind: EvidenceKind
    mine_id: uuid.UUID
    client_timestamp: datetime | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    gps_accuracy_m: float | None = Field(default=None, ge=0)
    location_method: LocationMethod = LocationMethod.NONE
    checkpoint_code: str | None = None
    mock_location_reported: bool | None = None
    device_fingerprint: str | None = None
    notes: str | None = None
    photo_hash: str | None = Field(default=None, max_length=64)

    findings: list[InspectionFindingIn] = Field(default_factory=list)
    attendance: AttendanceIn | None = None
    incident: IncidentIn | None = None


class FieldEvidenceOut(ORMModel):
    id: uuid.UUID
    client_uuid: str
    kind: EvidenceKind
    mine_id: uuid.UUID
    server_timestamp: datetime
    client_timestamp: datetime | None = None
    clock_skew_seconds: int | None = None
    location_method: LocationMethod
    spoof_flags: list[str] | None = None


class SyncAck(BaseModel):
    client_uuid: str
    id: uuid.UUID
    created: bool = Field(description="False when this record had already synced")
    spoof_flags: list[str] = Field(default_factory=list)
    server_timestamp: datetime
    capas_created: list[uuid.UUID] = Field(
        default_factory=list,
        description="CAPA items automatically raised by this sync, if any (e.g. a "
                    "non-compliant HIGH/CRITICAL inspection finding or incident).",
    )


# --- M4 ----------------------------------------------------------------
class CapaOut(ORMModel):
    id: uuid.UUID
    mine_id: uuid.UUID
    source_type: CapaSourceType
    rule_id: uuid.UUID | None = None
    description: str
    severity: Severity
    status: CapaStatus
    progress_percent: int
    assigned_to: uuid.UUID | None = None
    due_date: date | None = None
    escalation_level: int


class CapaCreate(BaseModel):
    mine_id: uuid.UUID
    source_type: CapaSourceType
    source_id: uuid.UUID | None = None
    rule_id: uuid.UUID | None = None
    description: str = Field(min_length=1)
    severity: Severity
    assigned_to: uuid.UUID | None = None
    due_date: date | None = None


class CapaTransition(BaseModel):
    to_status: CapaStatus
    note: str | None = None
    evidence_doc_id: uuid.UUID | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)


class CapaEventOut(ORMModel):
    id: uuid.UUID
    from_status: CapaStatus | None = None
    to_status: CapaStatus
    actor_id: uuid.UUID | None = None
    note: str | None = None
    created_at: datetime


# --- M5 ----------------------------------------------------------------
class ReadingIn(BaseModel):
    mine_id: uuid.UUID
    sensor_kind: SensorKind
    value: float
    unit: str = Field(min_length=1, max_length=24)
    recorded_at: datetime
    location_label: str | None = None
    # Simulated is the only honest default: no physical sensor is connected.
    provenance: DataProvenance = DataProvenance.SIMULATED


class ReadingOut(ORMModel):
    id: uuid.UUID
    mine_id: uuid.UUID
    sensor_kind: SensorKind
    value: float
    unit: str
    recorded_at: datetime
    provenance: DataProvenance


# --- M6 ----------------------------------------------------------------
class AuditEntryOut(ORMModel):
    seq: int
    actor_id: uuid.UUID | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    timestamp: datetime
    prev_hash: str
    row_hash: str


class ChainVerificationOut(BaseModel):
    intact: bool
    entries_checked: int
    broken_at_seq: int | None = None
    reason: str | None = None
    note: str

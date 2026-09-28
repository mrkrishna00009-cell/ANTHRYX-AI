"""Controlled vocabularies.

Stored as VARCHAR with a CHECK constraint (``native_enum=False``) rather
than a PostgreSQL ENUM type, so the same schema works on the PostgreSQL
primary and the SQLite development fallback without divergent migrations.
"""

from __future__ import annotations

import enum


class StrEnum(str, enum.Enum):
    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.value


# --- identity and access ---------------------------------------------
class Role(StrEnum):
    ADMIN = "ADMIN"
    DGMS_REGULATOR = "DGMS_REGULATOR"
    SUBSIDIARY_HEAD = "SUBSIDIARY_HEAD"
    MINE_MANAGER = "MINE_MANAGER"
    MINE_SAFETY_OFFICER = "MINE_SAFETY_OFFICER"
    FIELD_INSPECTOR = "FIELD_INSPECTOR"


# --- organisation -----------------------------------------------------
class MineType(StrEnum):
    UNDERGROUND = "UNDERGROUND"
    OPENCAST = "OPENCAST"
    MIXED = "MIXED"


class MineStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


# --- M0 statutory registry -------------------------------------------
class ObligationType(StrEnum):
    RECURRING_MEETING = "RECURRING_MEETING"
    RECURRING_INSPECTION = "RECURRING_INSPECTION"
    RECURRING_MEASUREMENT = "RECURRING_MEASUREMENT"
    CERTIFICATE_VALIDITY = "CERTIFICATE_VALIDITY"
    CONTINUOUS_STANDARD = "CONTINUOUS_STANDARD"
    EVENT_NOTIFICATION = "EVENT_NOTIFICATION"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ObligationStatus(StrEnum):
    """MISSING is the one that matters.

    An obligation the rule registry says applies, for which no evidence has
    ever been supplied, is invisible to a system that only tracks uploaded
    documents. That gap is the point of M0.
    """

    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    MISSING = "MISSING"


class ClauseVerification(StrEnum):
    """Whether a seeded clause reference has been checked against the statute."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"


# --- M1 documents ------------------------------------------------------
class VerificationStatus(StrEnum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class OcrEngine(StrEnum):
    TESSERACT = "TESSERACT"
    BHASHINI = "BHASHINI"
    DEMO_FALLBACK = "DEMO_FALLBACK"
    NONE = "NONE"


class ContractorStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    DEBARRED = "DEBARRED"


# --- M2 field evidence -------------------------------------------------
class EvidenceKind(StrEnum):
    INSPECTION = "INSPECTION"
    ATTENDANCE = "ATTENDANCE"
    INCIDENT = "INCIDENT"


class SyncStatus(StrEnum):
    PENDING_SYNC = "PENDING_SYNC"
    SYNCED = "SYNCED"


class LocationMethod(StrEnum):
    """GPS does not work underground. That is physics, not a bug."""

    GPS_SURFACE = "GPS_SURFACE"
    GPS_PIT_MOUTH = "GPS_PIT_MOUTH"
    QR_CHECKPOINT = "QR_CHECKPOINT"
    NFC_CHECKPOINT = "NFC_CHECKPOINT"
    NONE = "NONE"


class SpoofFlag(StrEnum):
    MOCK_LOCATION_REPORTED = "MOCK_LOCATION_REPORTED"
    UNREGISTERED_DEVICE = "UNREGISTERED_DEVICE"
    OUTSIDE_GEOFENCE = "OUTSIDE_GEOFENCE"
    CLOCK_SKEW = "CLOCK_SKEW"


class IncidentSource(StrEnum):
    FORM = "FORM"
    VOICE = "VOICE"


# --- M4 CAPA -----------------------------------------------------------
class CapaStatus(StrEnum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class GrievanceCategory(StrEnum):
    SAFETY_CONCERN = "SAFETY_CONCERN"
    WAGE_DISPUTE = "WAGE_DISPUTE"
    LAND_ENVIRONMENTAL = "LAND_ENVIRONMENTAL"
    HARASSMENT = "HARASSMENT"
    OTHER = "OTHER"


class GrievanceStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class ApprovalStage(StrEnum):
    MINE_MANAGER = "MINE_MANAGER"
    SUBSIDIARY_GM = "SUBSIDIARY_GM"
    CORPORATE_OFFICE = "CORPORATE_OFFICE"


class ApprovalDecision(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CapaSourceType(StrEnum):
    VIOLATION = "VIOLATION"
    RISK_ALERT = "RISK_ALERT"
    INCIDENT = "INCIDENT"
    SENSOR_ANOMALY = "SENSOR_ANOMALY"
    OBLIGATION_BREACH = "OBLIGATION_BREACH"


# --- M3 / M5 model outputs (deliberately distinct) ---------------------
class ModelKind(StrEnum):
    """M3 and M5 are separate systems and must never be conflated.

    An isolation-forest anomaly score is not an accident probability.
    """

    ACCIDENT_RISK_SUPERVISED = "ACCIDENT_RISK_SUPERVISED"
    SENSOR_ANOMALY_ISOLATION_FOREST = "SENSOR_ANOMALY_ISOLATION_FOREST"
    RULE_BASED_BASELINE = "RULE_BASED_BASELINE"


class ModelStatus(StrEnum):
    UNTRAINED = "UNTRAINED"
    TRAINED = "TRAINED"
    ARTIFACT_MISSING = "ARTIFACT_MISSING"


# --- provenance and providers -----------------------------------------
class DataProvenance(StrEnum):
    """Every externally sourced or generated value declares its origin."""

    REAL_PUBLIC_DATA = "REAL_PUBLIC_DATA"
    SIMULATED = "SIMULATED"
    DEMO = "DEMO"
    LIVE_EXTERNAL_API = "LIVE_EXTERNAL_API"
    DEMO_FALLBACK = "DEMO_FALLBACK"
    USER_SUPPLIED = "USER_SUPPLIED"


class ProviderStatus(StrEnum):
    LIVE_BHASHINI = "LIVE_BHASHINI"
    BHASHINI_UNAVAILABLE = "BHASHINI_UNAVAILABLE"
    DEMO_FALLBACK = "DEMO_FALLBACK"
    TESSERACT_LOCAL = "TESSERACT_LOCAL"


class SensorKind(StrEnum):
    METHANE = "METHANE"
    CARBON_MONOXIDE = "CARBON_MONOXIDE"
    AIRFLOW = "AIRFLOW"


class ReportKind(StrEnum):
    REPRESENTATIVE_STATUTORY_RETURN = "REPRESENTATIVE_STATUTORY_RETURN"
    COMPLIANCE_SUMMARY = "COMPLIANCE_SUMMARY"


class NotificationChannel(StrEnum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"

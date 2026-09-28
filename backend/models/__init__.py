"""SQLAlchemy models for ANTHRYX AI.

Importing this package registers every table on ``Base.metadata``, which
is what Alembic autogeneration and ``create_all`` rely on.

NOTE: an earlier documented decision (F6) explicitly excluded a
``grievances`` table from the schema. A later, explicit product
instruction asked for a genuine Grievance module with real persistence,
SLA tracking, and escalation - that instruction supersedes F6 for this
one item, and the supersession is recorded here rather than silently
applied. ``production_records`` remains deliberately absent per F6;
``production_hours`` survives as a column on ``mines`` and
``ml_features``; ``environmental_readings`` survives as M5 simulated
telemetry.
"""

from models.base import Base, TimestampMixin, UuidPkMixin, enum_column, utcnow
from models.approval import ApprovalChain, ApprovalStep
from models.capa import CapaEvent, CapaItem
from models.documents import Contractor, ContractorSite, Document, ExtractedField
from models.environment import EnvironmentalReading
from models.field_evidence import (
    AttendanceRecord, FieldEvidence, IncidentReport, InspectionFinding,
)
from models.grievance import Grievance, GrievanceEvent
from models.identity import User
from models.ml import (
    AnomalyExplanation, MlFeature, MlPrediction, ModelArtifactRecord,
)
from models.organisation import Device, Mine, Subsidiary
from models.reporting import AuditLogEntry, Notification, Report
from models.statutory import MineObligation, StatutoryRule

__all__ = [
    "Base", "TimestampMixin", "UuidPkMixin", "enum_column", "utcnow",
    "User", "Subsidiary", "Mine", "Device",
    "StatutoryRule", "MineObligation",
    "Document", "ExtractedField", "Contractor", "ContractorSite",
    "FieldEvidence", "InspectionFinding", "AttendanceRecord", "IncidentReport",
    "CapaItem", "CapaEvent",
    "Grievance", "GrievanceEvent",
    "ApprovalChain", "ApprovalStep",
    "EnvironmentalReading",
    "MlFeature", "MlPrediction", "AnomalyExplanation", "ModelArtifactRecord",
    "Report", "AuditLogEntry", "Notification",
]

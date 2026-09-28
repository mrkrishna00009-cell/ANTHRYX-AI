"""Mine Risk Timeline.

A real chronological aggregation of events already persisted by other
modules - never a new event log, never fabricated history. Every event
below is read from a table that some other, already-verified module
wrote to during its own normal operation:

  InspectionFinding  (via FieldEvidence)  - M2/M0
  IncidentReport     (via FieldEvidence)  - M2
  CapaItem creation + CapaEvent           - M4
  MlPrediction                            - M3
  AnomalyExplanation                      - M5
  GrievanceEvent (via Grievance)          - Grievances

If a mine genuinely has no events yet, the timeline is genuinely empty -
never padded with an invented entry.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.capa import CapaEvent, CapaItem
from models.field_evidence import FieldEvidence, IncidentReport, InspectionFinding
from models.grievance import Grievance, GrievanceEvent
from models.ml import AnomalyExplanation, MlPrediction


@dataclass(frozen=True)
class TimelineEvent:
    timestamp: datetime
    event_type: str
    mine_id: uuid.UUID
    severity: str | None
    source: str
    actor_id: str | None
    status: str | None
    related_id: str
    explanation: str


def build_timeline(session: Session, mine_id: uuid.UUID, limit: int = 200) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []

    # --- M0/M2: inspection findings -------------------------------------
    findings = session.execute(
        select(InspectionFinding, FieldEvidence.server_timestamp)
        .join(FieldEvidence, FieldEvidence.id == InspectionFinding.evidence_id)
        .where(FieldEvidence.mine_id == mine_id)
    ).all()
    for f, ts in findings:
        events.append(TimelineEvent(
            timestamp=ts, event_type="INSPECTION_FINDING", mine_id=mine_id,
            severity=f.severity.value if f.severity else None, source="M0/M2",
            actor_id=None, status="NON_COMPLIANT" if f.compliant is False else "COMPLIANT",
            related_id=str(f.id),
            explanation=f"{f.question}" + (f" — {f.observation}" if f.observation else ""),
        ))

    # --- M2: incident reports --------------------------------------------
    incidents = session.execute(
        select(IncidentReport, FieldEvidence.server_timestamp)
        .join(FieldEvidence, FieldEvidence.id == IncidentReport.evidence_id)
        .where(FieldEvidence.mine_id == mine_id)
    ).all()
    for inc, ts in incidents:
        events.append(TimelineEvent(
            timestamp=ts, event_type="INCIDENT_REPORTED", mine_id=mine_id,
            severity=inc.severity.value if inc.severity else None, source=inc.source.value,
            actor_id=None, status=None, related_id=str(inc.id),
            explanation=f"{inc.category}: {inc.description_en or '(no description)'}",
        ))

    # --- M4: CAPA creation + every transition -----------------------------
    capas = session.execute(select(CapaItem).where(CapaItem.mine_id == mine_id)).scalars().all()
    for c in capas:
        events.append(TimelineEvent(
            timestamp=c.created_at, event_type="CAPA_CREATED", mine_id=mine_id,
            severity=c.severity.value if c.severity else None, source=c.source_type.value,
            actor_id=None, status=c.status.value, related_id=str(c.id),
            explanation=c.description,
        ))
    capa_ids = [c.id for c in capas]
    if capa_ids:
        capa_events = session.execute(select(CapaEvent).where(CapaEvent.capa_id.in_(capa_ids))).scalars().all()
        for ce in capa_events:
            events.append(TimelineEvent(
                timestamp=ce.created_at, event_type="CAPA_TRANSITION", mine_id=mine_id,
                severity=None, source="M4",
                actor_id=str(ce.actor_id) if ce.actor_id else None,
                status=ce.to_status.value, related_id=str(ce.capa_id),
                explanation=(
                    f"{ce.from_status.value if ce.from_status else '(created)'} -> {ce.to_status.value}"
                    + (f": {ce.note}" if ce.note else "")
                ),
            ))

    # --- M3: real risk predictions ----------------------------------------
    preds = session.execute(select(MlPrediction).where(MlPrediction.mine_id == mine_id)).scalars().all()
    for p in preds:
        events.append(TimelineEvent(
            timestamp=p.scored_at, event_type="M3_RISK_SCORED", mine_id=mine_id,
            severity=p.band, source="M3", actor_id=None, status=p.band,
            related_id=str(p.id),
            explanation=f"M3 risk score {p.score} ({p.band}) - ranking signal, not an accident probability.",
        ))

    # --- M5: real anomaly detections ---------------------------------------
    anomalies = session.execute(select(AnomalyExplanation).where(AnomalyExplanation.mine_id == mine_id)).scalars().all()
    for a in anomalies:
        events.append(TimelineEvent(
            timestamp=a.window_end, event_type="M5_ANOMALY_SCORED", mine_id=mine_id,
            severity=None, source="M5", actor_id=None,
            status="ANOMALOUS" if a.is_anomaly else "NORMAL", related_id=str(a.id),
            explanation=f"M5 anomaly score {a.anomaly_score} (SIMULATED telemetry) - never an accident-risk figure.",
        ))

    # --- Grievances (mine-relevant) ----------------------------------------
    grievance_ids = [g.id for g in session.execute(
        select(Grievance).where(Grievance.mine_id == mine_id)
    ).scalars().all()]
    if grievance_ids:
        g_events = session.execute(
            select(GrievanceEvent).where(GrievanceEvent.grievance_id.in_(grievance_ids))
        ).scalars().all()
        for ge in g_events:
            events.append(TimelineEvent(
                timestamp=ge.created_at, event_type="GRIEVANCE_TRANSITION", mine_id=mine_id,
                severity=None, source="Grievances",
                actor_id=str(ge.actor_id) if ge.actor_id else None,
                status=ge.to_status.value, related_id=str(ge.grievance_id),
                explanation=(
                    f"{ge.from_status.value if ge.from_status else '(filed)'} -> {ge.to_status.value}"
                    + (f": {ge.note}" if ge.note else "")
                ),
            ))

    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events[:limit]

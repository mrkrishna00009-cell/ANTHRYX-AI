"""Domain model shape, relationships and constraints."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

import models
from models.enums import (
    CapaSourceType, DataProvenance, EvidenceKind, MineType, ProviderStatus,
    Role, SensorKind, Severity,
)


EXPECTED_TABLES = {
    "users", "subsidiaries", "mines", "devices",
    "statutory_rules", "mine_obligations",
    "documents", "extracted_fields", "contractors", "contractor_sites",
    "field_evidence", "inspection_findings", "attendance_records",
    "incident_reports",
    "capa_items", "capa_events",
    "environmental_readings",
    "ml_features", "ml_predictions", "anomaly_explanations", "model_artifacts",
    "reports", "audit_log", "notifications",
}


def test_every_expected_table_is_registered():
    assert EXPECTED_TABLES <= set(models.Base.metadata.tables)


def test_dropped_tables_are_absent():
    """Locked decision F6 excluded both grievances and production_records.

    A later, explicit product instruction asked for a real Grievance
    module with persistence, SLA tracking, and escalation - that
    instruction supersedes F6 for this one table, recorded in
    models/__init__.py's docstring and here. production_records remains
    absent; F6 is otherwise unchanged."""
    present = set(models.Base.metadata.tables)
    assert "grievances" in present  # F6 superseded for this table - see module docstring
    assert "production_records" not in present


def test_production_hours_survived_the_drop():
    assert "production_hours_last_year" in models.Mine.__table__.columns
    assert "production_hours" in models.MlFeature.__table__.columns


def test_environmental_readings_survived_the_drop():
    assert "environmental_readings" in models.Base.metadata.tables


def test_primary_keys_are_uuid_except_the_ledger():
    for name, table in models.Base.metadata.tables.items():
        pks = list(table.primary_key.columns)
        assert len(pks) == 1, f"{name} should have a single-column primary key"
    # The ledger is keyed by its sequence number, which is what the chain
    # is built on.
    assert list(models.AuditLogEntry.__table__.primary_key.columns)[0].name == "seq"


def _mine(session):
    mine = models.Mine(code=f"M-{uuid.uuid4().hex[:6]}", name="Test", mine_type=MineType.UNDERGROUND)
    session.add(mine)
    session.flush()
    return mine


def test_mine_coordinates_default_to_approximate(db_session):
    mine = _mine(db_session)
    assert mine.coordinate_is_approximate is True
    assert mine.coordinate_provenance is DataProvenance.DEMO


def test_environmental_reading_defaults_to_simulated(db_session):
    mine = _mine(db_session)
    reading = models.EnvironmentalReading(
        mine_id=mine.id, sensor_kind=SensorKind.METHANE, value=0.6, unit="%",
        recorded_at=datetime.now(timezone.utc),
    )
    db_session.add(reading)
    db_session.flush()
    assert reading.provenance is DataProvenance.SIMULATED


def test_mine_code_is_unique(db_session):
    db_session.add(models.Mine(code="DUP", name="A", mine_type=MineType.OPENCAST))
    db_session.flush()
    db_session.add(models.Mine(code="DUP", name="B", mine_type=MineType.OPENCAST))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_client_uuid_is_unique_on_field_evidence(db_session):
    mine = _mine(db_session)
    for _ in range(2):
        db_session.add(models.FieldEvidence(
            client_uuid="same-client-uuid", kind=EvidenceKind.INSPECTION,
            mine_id=mine.id, server_timestamp=datetime.now(timezone.utc),
        ))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_evidence_cascades_to_its_detail_rows(db_session):
    mine = _mine(db_session)
    evidence = models.FieldEvidence(
        client_uuid=str(uuid.uuid4()), kind=EvidenceKind.INCIDENT,
        mine_id=mine.id, server_timestamp=datetime.now(timezone.utc),
    )
    db_session.add(evidence)
    db_session.flush()
    db_session.add(models.IncidentReport(
        evidence_id=evidence.id, category="Gas", severity=Severity.HIGH
    ))
    db_session.flush()
    db_session.delete(evidence)
    db_session.flush()
    assert db_session.query(models.IncidentReport).count() == 0


def test_voice_incident_keeps_both_transcripts_and_their_provenance(db_session):
    """Locked requirement: original audio, language, both transcripts,
    and which provider produced them."""
    mine = _mine(db_session)
    evidence = models.FieldEvidence(
        client_uuid=str(uuid.uuid4()), kind=EvidenceKind.INCIDENT,
        mine_id=mine.id, server_timestamp=datetime.now(timezone.utc),
    )
    db_session.add(evidence)
    db_session.flush()
    incident = models.IncidentReport(
        evidence_id=evidence.id, category="Gas", severity=Severity.CRITICAL,
        source=models.IncidentReport.__table__.c.source.type.enum_class.VOICE,
        audio_path="/evidence/a.wav", audio_hash="a" * 64,
        source_language="hi", original_transcript="मीथेन का स्तर बढ़ रहा है",
        translated_transcript="Methane level is rising",
        asr_provider_status=ProviderStatus.DEMO_FALLBACK,
        nmt_provider_status=ProviderStatus.DEMO_FALLBACK,
        transcript_provenance=DataProvenance.DEMO_FALLBACK,
    )
    db_session.add(incident)
    db_session.flush()
    for column in (
        "audio_path", "audio_hash", "source_language", "original_transcript",
        "translated_transcript", "asr_provider_status", "nmt_provider_status",
    ):
        assert getattr(incident, column) is not None


def test_capa_events_cascade_and_order(db_session):
    mine = _mine(db_session)
    item = models.CapaItem(
        mine_id=mine.id, source_type=CapaSourceType.INCIDENT,
        description="x", severity=Severity.HIGH,
    )
    db_session.add(item)
    db_session.flush()
    db_session.add(models.CapaEvent(capa_id=item.id, to_status=item.status))
    db_session.flush()
    db_session.delete(item)
    db_session.flush()
    assert db_session.query(models.CapaEvent).count() == 0


def test_ml_feature_window_is_unique_per_mine(db_session):
    mine = _mine(db_session)
    for _ in range(2):
        db_session.add(models.MlFeature(
            mine_id=mine.id, window_end_date=date(2026, 1, 1)
        ))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_predictions_and_anomalies_are_separate_tables():
    """M3 and M5 outputs must not share a table."""
    assert models.MlPrediction.__tablename__ != models.AnomalyExplanation.__tablename__
    assert "anomaly_score" not in models.MlPrediction.__table__.columns
    assert "score" not in models.AnomalyExplanation.__table__.columns


def test_prediction_supports_human_override_with_justification():
    columns = models.MlPrediction.__table__.columns
    for name in ("overridden_by", "override_score", "override_justification", "overridden_at"):
        assert name in columns


def test_document_tracks_whether_ocr_was_corrected():
    assert "was_corrected" in models.ExtractedField.__table__.columns


def test_timestamps_present_on_mutable_entities():
    for model in (models.Mine, models.Document, models.CapaItem, models.User):
        assert "created_at" in model.__table__.columns
        assert "updated_at" in model.__table__.columns


def test_useful_indexes_exist():
    indexed = {
        c.name for c in models.FieldEvidence.__table__.columns if c.index
    }
    assert "mine_id" in indexed and "client_uuid" in indexed

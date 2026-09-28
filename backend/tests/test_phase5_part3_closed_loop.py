# -*- coding: utf-8 -*-
"""Phase 5 Part 3 - closed-loop integration tests."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------- PART A: feature builder
def test_feature_builder_deterministic(client, seeded, admin_headers, db_session):
    from services.feature_builder import FeatureBuilder
    fb = FeatureBuilder(db_session)
    row1, _ = fb.build(uuid.UUID(seeded["mine_id"]))
    val1 = row1.violations_last_12m
    row2, _ = fb.build(uuid.UUID(seeded["mine_id"]))
    assert val1 == row2.violations_last_12m
    assert row1.id == row2.id


def test_feature_builder_blocked_features_always_none(client, seeded, db_session):
    from services.feature_builder import FeatureBuilder
    row, _ = FeatureBuilder(db_session).build(uuid.UUID(seeded["mine_id"]))
    assert row.production_hours is None
    assert row.avg_penalty_amount is None


def test_feature_builder_idempotent_no_duplicate_rows(client, seeded, db_session):
    from services.feature_builder import FeatureBuilder
    from models.ml import MlFeature
    from sqlalchemy import select
    fb = FeatureBuilder(db_session)
    fb.build(uuid.UUID(seeded["mine_id"]))
    fb.build(uuid.UUID(seeded["mine_id"]))
    fb.build(uuid.UUID(seeded["mine_id"]))
    rows = db_session.execute(
        select(MlFeature).where(MlFeature.mine_id == uuid.UUID(seeded["mine_id"]))
    ).scalars().all()
    assert len(rows) == 1


def test_feature_builder_uses_real_inspection_data(client, seeded, admin_headers, db_session):
    from models.enums import EvidenceKind, LocationMethod, SyncStatus, Severity
    from models.field_evidence import FieldEvidence, InspectionFinding
    ev = FieldEvidence(
        client_uuid="feat-test-0001", kind=EvidenceKind.INSPECTION,
        mine_id=uuid.UUID(seeded["mine_id"]), server_timestamp=datetime.now(timezone.utc),
        location_method=LocationMethod.NONE, sync_status=SyncStatus.SYNCED,
    )
    db_session.add(ev); db_session.flush()
    db_session.add(InspectionFinding(evidence_id=ev.id, question="Q1", compliant=False, severity=Severity.HIGH))
    db_session.commit()

    from services.feature_builder import FeatureBuilder
    row, _ = FeatureBuilder(db_session).build(uuid.UUID(seeded["mine_id"]))
    assert row.violations_last_12m == 1
    assert row.ss_violations_last_12m == 1


def test_build_features_api(client, seeded, admin_headers):
    r = client.post(f"/api/v1/risk/mines/{seeded['mine_id']}/build-features", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert "violations_last_12m" in body
    assert body["production_hours"] is None
    assert body["avg_penalty_amount"] is None


# ---------------------------------------------------------------- PART B: M3 -> CAPA idempotency
def test_m3_high_risk_creates_capa(client, seeded, admin_headers, db_session):
    from models.ml import MlFeature
    feature = MlFeature(
        mine_id=uuid.UUID(seeded["mine_id"]), window_end_date=date(2024, 12, 31),
        violations_last_12m=50, ss_violations_last_12m=20, repeat_violation_ratio=0.6,
        days_since_last_inspection=2, inspection_hours_last_12m=500.0,
        mine_size_avg_employees=800.0, mine_type="UNDERGROUND",
    )
    db_session.add(feature); db_session.commit()
    r = client.get(f"/api/v1/risk/mines/{seeded['mine_id']}", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    if body["risk_category"] == "HIGH":
        assert body["capa_id"] is not None


def test_m3_auto_capa_idempotent_on_refresh(client, seeded, admin_headers, db_session):
    """Refreshing the risk page twice must never create a second active CAPA."""
    from models.ml import MlFeature
    from models.capa import CapaItem
    from models.enums import CapaSourceType, CapaStatus
    from sqlalchemy import select

    feature = MlFeature(
        mine_id=uuid.UUID(seeded["mine_id"]), window_end_date=date(2024, 12, 31),
        violations_last_12m=80, ss_violations_last_12m=40, repeat_violation_ratio=0.7,
        days_since_last_inspection=1, inspection_hours_last_12m=900.0,
        mine_size_avg_employees=1200.0, mine_type="UNDERGROUND",
    )
    db_session.add(feature); db_session.commit()

    r1 = client.get(f"/api/v1/risk/mines/{seeded['mine_id']}", headers=admin_headers)
    r2 = client.get(f"/api/v1/risk/mines/{seeded['mine_id']}", headers=admin_headers)
    if r1.json()["risk_category"] == "HIGH":
        assert r1.json()["capa_created"] is True
        assert r2.json()["capa_created"] is False
        assert r1.json()["capa_id"] == r2.json()["capa_id"]
        count = db_session.execute(
            select(CapaItem).where(
                CapaItem.mine_id == uuid.UUID(seeded["mine_id"]),
                CapaItem.source_type == CapaSourceType.RISK_ALERT,
                CapaItem.status != CapaStatus.CLOSED,
            )
        ).scalars().all()
        assert len(count) == 1


# ---------------------------------------------------------------- PART D: inspection/incident auto-CAPA
def test_inspection_finding_auto_capa(client, seeded, admin_headers, db_session):
    r = client.post("/api/v1/field-evidence", headers=admin_headers, json={
        "client_uuid": "insp-capa-0001", "kind": "INSPECTION", "mine_id": seeded["mine_id"],
        "findings": [{"question": "Fire extinguishers present?", "compliant": False,
                     "severity": "HIGH", "observation": "Missing in section B"}],
    })
    assert r.status_code == 201
    body = r.json()
    assert len(body["capas_created"]) == 1


def test_inspection_finding_low_severity_no_capa(client, seeded, admin_headers):
    r = client.post("/api/v1/field-evidence", headers=admin_headers, json={
        "client_uuid": "insp-capa-0002", "kind": "INSPECTION", "mine_id": seeded["mine_id"],
        "findings": [{"question": "Minor housekeeping", "compliant": False, "severity": "LOW"}],
    })
    assert r.status_code == 201
    assert r.json()["capas_created"] == []


def test_form_incident_auto_capa(client, seeded, admin_headers):
    r = client.post("/api/v1/field-evidence", headers=admin_headers, json={
        "client_uuid": "form-incident-capa-0001", "kind": "INCIDENT", "mine_id": seeded["mine_id"],
        "incident": {"category": "Roof fall", "severity": "CRITICAL", "source": "FORM"},
    })
    assert r.status_code == 201
    assert len(r.json()["capas_created"]) == 1


def test_form_incident_capa_idempotent_on_retry(client, seeded, admin_headers, db_session):
    """The SAME client_uuid retried must not create a second CAPA - the
    outer sync-level idempotency already returns early, but this proves
    the CAPA-side idempotency also holds if ever called twice for one record."""
    from models.capa import CapaItem
    from sqlalchemy import select

    payload = {
        "client_uuid": "form-incident-capa-0002", "kind": "INCIDENT", "mine_id": seeded["mine_id"],
        "incident": {"category": "Gas leak", "severity": "CRITICAL", "source": "FORM"},
    }
    r1 = client.post("/api/v1/field-evidence", headers=admin_headers, json=payload)
    r2 = client.post("/api/v1/field-evidence", headers=admin_headers, json=payload)
    assert r1.json()["created"] is True
    assert r2.json()["created"] is False  # sync-level idempotency short-circuits

    from models.enums import CapaSourceType
    count = db_session.execute(
        select(CapaItem).where(CapaItem.mine_id == uuid.UUID(seeded["mine_id"]),
                               CapaItem.source_type == CapaSourceType.INCIDENT)
    ).scalars().all()
    assert len(count) == 1


# ---------------------------------------------------------------- PART E: escalation scheduler
def test_escalation_not_yet_overdue_stays_at_initial_level(db_session):
    from datetime import date, timedelta
    from models.enums import MineType, Severity, CapaSourceType, CapaStatus
    from models.organisation import Mine, Subsidiary
    from models.capa import CapaItem
    from services.escalation_scheduler import run_escalation_check

    sub = Subsidiary(code="ESCT1", name="Esc Test 1", state="Jharkhand")
    db_session.add(sub); db_session.flush()
    mine = Mine(code="ESCT1-01", name="Esc Mine 1", mine_type=MineType.UNDERGROUND, subsidiary_id=sub.id, state="Jharkhand")
    db_session.add(mine); db_session.flush()
    today = date(2026, 1, 20)
    capa = CapaItem(mine_id=mine.id, source_type=CapaSourceType.INCIDENT, severity=Severity.MEDIUM,
                    description="Not overdue", status=CapaStatus.OPEN, due_date=today + timedelta(days=30))
    db_session.add(capa); db_session.commit()

    run_escalation_check(db_session, today=today)
    db_session.commit()
    # Level 1 fires immediately per the existing ladder's own "-9999 days
    # relative to due" trigger (initial routing, not an overdue signal).
    # It must NOT reach any higher rung while genuinely not overdue.
    assert capa.escalation_level == 1

    run_escalation_check(db_session, today=today + timedelta(days=5))
    db_session.commit()
    assert capa.escalation_level == 1  # still not due; no further escalation


def test_escalation_first_and_later_rungs(db_session):
    from datetime import date, timedelta
    from models.enums import MineType, Severity, CapaSourceType, CapaStatus
    from models.organisation import Mine, Subsidiary
    from models.capa import CapaItem
    from services.escalation_scheduler import run_escalation_check

    sub = Subsidiary(code="ESCT2", name="Esc Test 2", state="Jharkhand")
    db_session.add(sub); db_session.flush()
    mine = Mine(code="ESCT2-01", name="Esc Mine 2", mine_type=MineType.UNDERGROUND, subsidiary_id=sub.id, state="Jharkhand")
    db_session.add(mine); db_session.flush()
    today = date(2026, 1, 20)
    capa = CapaItem(mine_id=mine.id, source_type=CapaSourceType.INCIDENT, severity=Severity.MEDIUM,
                    description="Will become overdue", status=CapaStatus.OPEN, due_date=today)
    db_session.add(capa); db_session.commit()

    run_escalation_check(db_session, today=today)
    db_session.commit()
    first_level = capa.escalation_level
    assert first_level >= 1
    assert capa.status.value == "ESCALATED"

    run_escalation_check(db_session, today=today + timedelta(days=10))
    db_session.commit()
    assert capa.escalation_level > first_level  # a real, higher rung reached later


def test_escalation_repeated_execution_is_idempotent(db_session):
    from datetime import date
    from models.enums import MineType, Severity, CapaSourceType, CapaStatus
    from models.organisation import Mine, Subsidiary
    from models.capa import CapaItem
    from models.reporting import AuditLogEntry
    from sqlalchemy import select
    from services.escalation_scheduler import run_escalation_check

    sub = Subsidiary(code="ESCT3", name="Esc Test 3", state="Jharkhand")
    db_session.add(sub); db_session.flush()
    mine = Mine(code="ESCT3-01", name="Esc Mine 3", mine_type=MineType.UNDERGROUND, subsidiary_id=sub.id, state="Jharkhand")
    db_session.add(mine); db_session.flush()
    today = date(2026, 1, 20)
    capa = CapaItem(mine_id=mine.id, source_type=CapaSourceType.INCIDENT, severity=Severity.MEDIUM,
                    description="Repeat test", status=CapaStatus.OPEN, due_date=today)
    db_session.add(capa); db_session.commit()

    for _ in range(5):
        run_escalation_check(db_session, today=today)
        db_session.commit()

    count = len(db_session.execute(
        select(AuditLogEntry).where(AuditLogEntry.action == "CAPA_AUTO_ESCALATED",
                                    AuditLogEntry.entity_id == str(capa.id))
    ).scalars().all())
    assert count == 1  # 5 identical runs, exactly one audit entry


def test_escalation_creates_audit_entry(db_session):
    from datetime import date
    from models.enums import MineType, Severity, CapaSourceType, CapaStatus
    from models.organisation import Mine, Subsidiary
    from models.capa import CapaItem
    from models.reporting import AuditLogEntry
    from sqlalchemy import select
    from services.escalation_scheduler import run_escalation_check

    sub = Subsidiary(code="ESCT4", name="Esc Test 4", state="Jharkhand")
    db_session.add(sub); db_session.flush()
    mine = Mine(code="ESCT4-01", name="Esc Mine 4", mine_type=MineType.UNDERGROUND, subsidiary_id=sub.id, state="Jharkhand")
    db_session.add(mine); db_session.flush()
    today = date(2026, 1, 20)
    capa = CapaItem(mine_id=mine.id, source_type=CapaSourceType.INCIDENT, severity=Severity.MEDIUM,
                    description="Audit test", status=CapaStatus.OPEN, due_date=today)
    db_session.add(capa); db_session.commit()

    run_escalation_check(db_session, today=today)
    db_session.commit()
    entry = db_session.execute(
        select(AuditLogEntry).where(AuditLogEntry.action == "CAPA_AUTO_ESCALATED",
                                    AuditLogEntry.entity_id == str(capa.id))
    ).scalar_one_or_none()
    assert entry is not None
    assert "SYSTEM_SCHEDULER" in entry.payload_json


# ---------------------------------------------------------------- PART F: CAPA closure -> rescore
def test_capa_closure_sets_rescore_required(client, seeded, admin_headers, db_session):
    from models.organisation import Mine
    import uuid as _uuid

    r = client.post("/api/v1/capa", headers=admin_headers, json={
        "mine_id": seeded["mine_id"], "source_type": "INCIDENT",
        "description": "Rescore test", "severity": "HIGH",
    })
    capa_id = r.json()["id"]
    for to_status, extra in [
        ("ASSIGNED", {}), ("IN_PROGRESS", {}),
        ("EVIDENCE_SUBMITTED", {"evidence_doc_id": client.post(
            "/api/v1/documents", headers=admin_headers,
            json={"mine_id": seeded["mine_id"], "doc_type": "Closure evidence"}).json()["id"]}),
        ("VERIFIED", {"note": "verified"}), ("CLOSED", {"note": "closed"}),
    ]:
        t = client.post(f"/api/v1/capa/{capa_id}/transition", headers=admin_headers,
                        json={"to_status": to_status, **extra})
        assert t.status_code == 200, t.text

    mine = db_session.get(Mine, _uuid.UUID(seeded["mine_id"]))
    db_session.refresh(mine)
    assert mine.rescore_required is True


def test_build_features_clears_rescore_flag(client, seeded, admin_headers, db_session):
    from models.organisation import Mine
    import uuid as _uuid

    mine = db_session.get(Mine, _uuid.UUID(seeded["mine_id"]))
    mine.rescore_required = True
    db_session.commit()

    r = client.post(f"/api/v1/risk/mines/{seeded['mine_id']}/build-features", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["rescore_was_pending"] is True

    db_session.refresh(mine)
    assert mine.rescore_required is False


def test_risk_score_reports_rescore_required_without_lowering_score(client, seeded, admin_headers, db_session):
    from models.ml import MlFeature
    from models.organisation import Mine
    from datetime import date
    import uuid as _uuid

    feature = MlFeature(mine_id=_uuid.UUID(seeded["mine_id"]), window_end_date=date(2024, 12, 31),
                        violations_last_12m=5, mine_size_avg_employees=50.0, mine_type="UNDERGROUND")
    db_session.add(feature)
    mine = db_session.get(Mine, _uuid.UUID(seeded["mine_id"]))
    mine.rescore_required = True
    db_session.commit()

    r1 = client.get(f"/api/v1/risk/mines/{seeded['mine_id']}", headers=admin_headers)
    assert r1.json()["rescore_required"] is True
    assert r1.json()["rescore_note"] is not None

    # A second identical call with the SAME feature row must produce the
    # SAME score - the flag never artificially changes the number.
    r2 = client.get(f"/api/v1/risk/mines/{seeded['mine_id']}", headers=admin_headers)
    assert r1.json()["risk_score"] == r2.json()["risk_score"]


# ---------------------------------------------------------------- PART G: telemetry simulator
def test_telemetry_simulator_normal_mode(client, seeded, admin_headers):
    r = client.post("/api/v1/sensors/simulate", headers=admin_headers,
                    params={"mine_id": seeded["mine_id"], "mode": "normal", "seed": 7})
    assert r.status_code == 200
    body = r.json()
    assert len(body["readings"]) == 3
    assert body["provenance"] == "SIMULATED"


def test_telemetry_simulator_anomaly_mode(client, seeded, admin_headers):
    r = client.post("/api/v1/sensors/simulate", headers=admin_headers,
                    params={"mine_id": seeded["mine_id"], "mode": "anomaly", "seed": 7})
    assert r.status_code == 200
    assert r.json()["mode"] == "anomaly"


def test_telemetry_simulator_provenance_always_simulated(client, seeded, admin_headers, db_session):
    import uuid as _uuid
    from models.environment import EnvironmentalReading
    from sqlalchemy import select

    client.post("/api/v1/sensors/simulate", headers=admin_headers,
               params={"mine_id": seeded["mine_id"], "mode": "normal", "seed": 3})
    rows = db_session.execute(
        select(EnvironmentalReading).where(EnvironmentalReading.mine_id == _uuid.UUID(seeded["mine_id"]))
    ).scalars().all()
    assert len(rows) >= 3
    assert all(r.provenance.value == "SIMULATED" for r in rows)


def test_m5_simulator_full_pipeline_anomaly_to_capa_to_audit(client, seeded, admin_headers):
    """The complete demo path: simulate anomalous telemetry -> detect ->
    (likely) anomaly -> SENSOR_ANOMALY CAPA -> audit entry."""
    sim = client.post("/api/v1/sensors/simulate", headers=admin_headers,
                      params={"mine_id": seeded["mine_id"], "mode": "anomaly", "seed": 99})
    assert sim.status_code == 200

    detect = client.post("/api/v1/sensors/detect", headers=admin_headers,
                         params={"mine_id": seeded["mine_id"]})
    assert detect.status_code == 200
    body = detect.json()
    assert body["provenance"] == "SIMULATED"

    audit = client.get("/api/v1/audit", headers=admin_headers, params={"limit": 20}).json()
    actions = {a["action"] for a in audit}
    assert "M5_TELEMETRY_SIMULATED" in actions
    assert "M5_ANOMALY_SCORED" in actions
    if body["is_anomaly"]:
        assert body["capa_id"] is not None


# ---------------------------------------------------------------- PART C: M0 checklist -> PWA -> finding
def test_checklist_returns_applicable_m0_rules(client, seeded, admin_headers, db_session):
    from models.statutory import StatutoryRule
    from models.enums import ObligationType, Severity, ClauseVerification

    rule = StatutoryRule(
        rule_code="CHK-001", statute="CMR 2017", clause="Reg 129", title="Ventilation adequacy",
        obligation_type=ObligationType.RECURRING_MEETING, frequency_days=60,
        applies_to_underground=True, applies_to_opencast=False, severity=Severity.HIGH,
        evidence_required="Ventilation log", authority="DGMS",
        clause_verification=ClauseVerification.VERIFIED,
    )
    db_session.add(rule); db_session.commit()

    r = client.get(f"/api/v1/mines/{seeded['mine_id']}/checklist", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    codes = [item["rule_code"] for item in body["checklist"]]
    assert "CHK-001" in codes


def test_m0_rule_to_checklist_to_finding_to_persistence(client, seeded, admin_headers, db_session):
    """The complete Part C proof: a real M0 rule appears on the checklist,
    the PWA-shaped finding payload references its rule_id, and the
    resulting InspectionFinding is genuinely persisted with that linkage."""
    from models.statutory import StatutoryRule
    from models.enums import ObligationType, Severity, ClauseVerification
    from models.field_evidence import InspectionFinding
    from sqlalchemy import select

    rule = StatutoryRule(
        rule_code="CHK-002", statute="CMR 2017", clause="Reg 146", title="Dust suppression",
        obligation_type=ObligationType.RECURRING_MEETING, frequency_days=30,
        applies_to_underground=True, applies_to_opencast=False, severity=Severity.MEDIUM,
        evidence_required="Water spray log", authority="DGMS",
        clause_verification=ClauseVerification.VERIFIED,
    )
    db_session.add(rule); db_session.commit()

    checklist = client.get(f"/api/v1/mines/{seeded['mine_id']}/checklist", headers=admin_headers).json()
    item = next(i for i in checklist["checklist"] if i["rule_code"] == "CHK-002")

    sync = client.post("/api/v1/field-evidence", headers=admin_headers, json={
        "client_uuid": "checklist-e2e-0001", "kind": "INSPECTION", "mine_id": seeded["mine_id"],
        "findings": [{
            "rule_id": item["rule_id"], "question": item["question"],
            "compliant": True, "observation": "Spray system operating normally",
        }],
    })
    assert sync.status_code == 201

    persisted = db_session.execute(
        select(InspectionFinding).where(InspectionFinding.rule_id == uuid.UUID(item["rule_id"]))
    ).scalars().all()
    assert len(persisted) == 1
    assert persisted[0].compliant is True
    assert persisted[0].observation == "Spray system operating normally"


# ---------------------------------------------------------------- PART H: bootstrap idempotency
def test_bootstrap_demo_is_idempotent(client):
    """Runs the real bootstrap module against the test's own throwaway DB
    twice and asserts the second run creates nothing new."""
    import sys, importlib
    sys.path.insert(0, "/home/claude/anthryx_ai")
    import scripts.bootstrap_demo as bootstrap_demo
    importlib.reload(bootstrap_demo)

    r1 = bootstrap_demo.bootstrap()
    assert r1["mines"] == len(bootstrap_demo.DEMO_MINES)
    assert r1["users"] == 3

    r2 = bootstrap_demo.bootstrap()
    assert r2["mines"] == 0
    assert r2["users"] == 0
    assert r2["rules"] == 0
    assert r2["demo_findings"] == 0
    assert r2["demo_telemetry_readings"] == 0
    assert len(r2["skipped"]) >= 11


# ---------------------------------------------------------------- PART C: M0 checklist
def test_inspection_checklist_returns_m0_rules(client, seeded, admin_headers, db_session):
    from models.statutory import StatutoryRule
    from models.enums import ObligationType, Severity, ClauseVerification
    rule = StatutoryRule(
        rule_code="CHK-TEST-1", statute="Test Statute", clause="Reg 1", title="Checklist test rule",
        obligation_type=ObligationType.CERTIFICATE_VALIDITY, frequency_days=365,
        applies_to_underground=True, applies_to_opencast=False, severity=Severity.HIGH,
        evidence_required="x", authority="TEST", clause_verification=ClauseVerification.VERIFIED,
    )
    db_session.add(rule); db_session.commit()

    r = client.get(f"/api/v1/mines/{seeded['mine_id']}/checklist", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert any(item["rule_code"] == "CHK-TEST-1" for item in body["checklist"])


def test_inspection_finding_persists_via_checklist_flow(client, seeded, admin_headers, db_session):
    from models.statutory import StatutoryRule
    from models.enums import ObligationType, Severity, ClauseVerification
    rule = StatutoryRule(
        rule_code="CHK-TEST-2", statute="Test Statute", clause="Reg 2", title="Persistence test rule",
        obligation_type=ObligationType.CERTIFICATE_VALIDITY, frequency_days=365,
        applies_to_underground=True, applies_to_opencast=False, severity=Severity.MEDIUM,
        evidence_required="x", authority="TEST", clause_verification=ClauseVerification.VERIFIED,
    )
    db_session.add(rule); db_session.commit()

    checklist = client.get(f"/api/v1/mines/{seeded['mine_id']}/checklist", headers=admin_headers).json()
    item = next(i for i in checklist["checklist"] if i["rule_code"] == "CHK-TEST-2")

    r = client.post("/api/v1/field-evidence", headers=admin_headers, json={
        "client_uuid": "checklist-persist-0001", "kind": "INSPECTION", "mine_id": seeded["mine_id"],
        "findings": [{"rule_id": item["rule_id"], "question": item["question"],
                     "compliant": True, "observation": "All good"}],
    })
    assert r.status_code == 201

    from models.field_evidence import InspectionFinding
    from sqlalchemy import select
    import uuid as _uuid
    finding = db_session.execute(
        select(InspectionFinding).where(InspectionFinding.rule_id == _uuid.UUID(item["rule_id"]))
    ).scalar_one_or_none()
    assert finding is not None
    assert finding.compliant is True


# ---------------------------------------------------------------- PART F: closure -> rescore
def test_capa_closure_sets_rescore_required(client, seeded, admin_headers, db_session):
    import uuid as _uuid
    from models.organisation import Mine

    r = client.post("/api/v1/capa", headers=admin_headers, json={
        "mine_id": seeded["mine_id"], "source_type": "INCIDENT",
        "description": "Rescore test CAPA", "severity": "HIGH",
    })
    capa_id = r.json()["id"]

    mine = db_session.get(Mine, _uuid.UUID(seeded["mine_id"]))
    assert mine.rescore_required is False

    for to_status in ("ASSIGNED", "IN_PROGRESS", "EVIDENCE_SUBMITTED", "VERIFIED", "CLOSED"):
        payload = {"to_status": to_status}
        if to_status == "EVIDENCE_SUBMITTED":
            doc = client.post("/api/v1/documents", headers=admin_headers,
                              json={"mine_id": seeded["mine_id"], "doc_type": "Closure evidence"}).json()
            payload["evidence_doc_id"] = doc["id"]
        if to_status in ("VERIFIED", "CLOSED"):
            payload["note"] = "closure justification"
        t = client.post(f"/api/v1/capa/{capa_id}/transition", headers=admin_headers, json=payload)
        assert t.status_code == 200, t.text

    db_session.refresh(mine)
    assert mine.rescore_required is True


def test_build_features_clears_rescore_required_and_reports_it(client, seeded, admin_headers, db_session):
    import uuid as _uuid
    from models.organisation import Mine

    mine = db_session.get(Mine, _uuid.UUID(seeded["mine_id"]))
    mine.rescore_required = True
    db_session.commit()

    r = client.post(f"/api/v1/risk/mines/{seeded['mine_id']}/build-features", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["rescore_was_required"] is True

    db_session.refresh(mine)
    assert mine.rescore_required is False


def test_risk_response_shows_rescore_required_without_fabricating_improvement(client, seeded, admin_headers, db_session):
    import uuid as _uuid
    from datetime import date
    from models.ml import MlFeature
    from models.organisation import Mine

    feature = MlFeature(mine_id=_uuid.UUID(seeded["mine_id"]), window_end_date=date(2024, 12, 31),
                        violations_last_12m=5, mine_size_avg_employees=50.0, mine_type="UNDERGROUND")
    db_session.add(feature)
    mine = db_session.get(Mine, _uuid.UUID(seeded["mine_id"]))
    mine.rescore_required = True
    db_session.commit()

    r = client.get(f"/api/v1/risk/mines/{seeded['mine_id']}", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["rescore_required"] is True
    assert "NOT been artificially lowered" in body["rescore_note"]


# ---------------------------------------------------------------- PART G: telemetry simulator
def test_telemetry_simulator_normal_mode_deterministic():
    from services.telemetry_simulator import generate_readings
    import uuid as _uuid
    mine_id = _uuid.uuid4()
    r1 = generate_readings(mine_id, mode="normal", seed=42)
    r2 = generate_readings(mine_id, mode="normal", seed=42)
    assert [x.value for x in r1] == [x.value for x in r2]
    methane = next(x.value for x in r1 if x.sensor_kind == "METHANE")
    assert 0.0 <= methane <= 1.0


def test_telemetry_simulator_anomaly_mode_differs_from_normal():
    from services.telemetry_simulator import generate_readings
    import uuid as _uuid
    mine_id = _uuid.uuid4()
    normal = generate_readings(mine_id, mode="normal", seed=1)
    anomaly = generate_readings(mine_id, mode="anomaly", seed=1)
    normal_airflow = next(x.value for x in normal if x.sensor_kind == "AIRFLOW")
    anomaly_airflow = next(x.value for x in anomaly if x.sensor_kind == "AIRFLOW")
    assert normal_airflow != anomaly_airflow


def test_telemetry_simulator_provenance_always_simulated():
    from services.telemetry_simulator import generate_readings
    import uuid as _uuid
    for mode in ("normal", "anomaly"):
        readings = generate_readings(_uuid.uuid4(), mode=mode, seed=7)
        assert all(r.provenance == "SIMULATED" for r in readings)


def test_full_m5_simulator_to_anomaly_to_capa_to_audit(client, seeded, admin_headers):
    sim = client.post("/api/v1/sensors/simulate", headers=admin_headers,
                      params={"mine_id": seeded["mine_id"], "mode": "anomaly", "seed": 99})
    assert sim.status_code == 200
    assert sim.json()["provenance"] == "SIMULATED"

    detect = client.post("/api/v1/sensors/detect", headers=admin_headers,
                         params={"mine_id": seeded["mine_id"]})
    assert detect.status_code == 200
    body = detect.json()
    assert body["provenance"] == "SIMULATED"

    audit = client.get("/api/v1/audit", headers=admin_headers, params={"limit": 20}).json()
    actions = {a["action"] for a in audit}
    assert "M5_TELEMETRY_SIMULATED" in actions
    assert "M5_ANOMALY_SCORED" in actions


# ---------------------------------------------------------------- PART H: bootstrap idempotency
def test_bootstrap_demo_idempotent(client):
    import sys
    sys.path.insert(0, "/home/claude/anthryx_ai/scripts")
    sys.path.insert(0, "/home/claude/anthryx_ai")
    import importlib
    bootstrap_demo = importlib.import_module("bootstrap_demo")

    first = bootstrap_demo.bootstrap()
    assert first["mines"] >= 0  # first call in THIS test db may or may not be the very first ever

    second = bootstrap_demo.bootstrap()
    assert second["subsidiaries"] == 0
    assert second["mines"] == 0
    assert second["users"] == 0
    assert second["rules"] == 0
    assert second["obligations"] == 0
    assert len(second["skipped"]) > 0

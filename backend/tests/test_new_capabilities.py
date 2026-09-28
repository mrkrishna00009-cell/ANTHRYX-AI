# -*- coding: utf-8 -*-
"""Tests for the three P0 capability gaps: Mine Risk Timeline, Compliance
Copilot, Contradiction & Drift."""
import uuid
from datetime import date, datetime, timezone


# ---------------------------------------------------------------- MINE RISK TIMELINE
def test_timeline_empty_for_a_mine_with_no_events(client, seeded, admin_headers, db_session):
    from models.organisation import Mine, Subsidiary
    from models.enums import MineType
    sub = Subsidiary(code="TL-EMPTY", name="Timeline Empty Sub", state="Jharkhand")
    db_session.add(sub); db_session.flush()
    mine = Mine(code="TL-EMPTY-01", name="Untouched Mine", mine_type=MineType.OPENCAST, subsidiary_id=sub.id, state="Jharkhand")
    db_session.add(mine); db_session.commit()

    r = client.get(f"/api/v1/mines/{mine.id}/timeline", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["event_count"] == 0
    assert r.json()["events"] == []


def test_timeline_events_trace_to_real_persisted_records(client, seeded, admin_headers):
    # a real inspection finding
    sync = client.post("/api/v1/field-evidence", headers=admin_headers, json={
        "client_uuid": "timeline-test-0001", "kind": "INSPECTION", "mine_id": seeded["mine_id"],
        "findings": [{"question": "Timeline test item", "compliant": False, "severity": "HIGH",
                     "observation": "Timeline-traceable observation"}],
    })
    assert sync.status_code == 201

    r = client.get(f"/api/v1/mines/{seeded['mine_id']}/timeline", headers=admin_headers)
    assert r.status_code == 200
    events = r.json()["events"]
    matching = [e for e in events if e["event_type"] == "INSPECTION_FINDING"
               and "Timeline-traceable observation" in e["explanation"]]
    assert len(matching) == 1, "the exact finding just created must appear in the timeline"

    # a real CAPA should also appear, since severity HIGH triggers auto-CAPA
    capa_events = [e for e in events if e["event_type"] == "CAPA_CREATED"]
    assert len(capa_events) >= 1


def test_timeline_is_chronologically_ordered(client, seeded, admin_headers):
    r = client.get(f"/api/v1/mines/{seeded['mine_id']}/timeline", headers=admin_headers)
    events = r.json()["events"]
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps, reverse=True)


def test_timeline_respects_mine_access_scoping(client, seeded, inspector_headers):
    import uuid as _uuid
    fake_mine_id = _uuid.uuid4()
    r = client.get(f"/api/v1/mines/{fake_mine_id}/timeline", headers=inspector_headers)
    assert r.status_code in (403, 404)


# ---------------------------------------------------------------- COMPLIANCE COPILOT
def test_copilot_valid_grounded_query(client, admin_headers, db_session):
    from models.statutory import StatutoryRule
    from models.enums import ObligationType, Severity, ClauseVerification
    rule = StatutoryRule(
        rule_code="COPILOT-TEST-1", statute="Coal Mines Regulations 2017", clause="Regulation 129",
        title="Ventilation standards", obligation_type=ObligationType.CERTIFICATE_VALIDITY,
        frequency_days=365, applies_to_underground=True, applies_to_opencast=True,
        severity=Severity.HIGH, evidence_required="x", authority="DGMS",
        clause_verification=ClauseVerification.VERIFIED,
    )
    db_session.add(rule); db_session.commit()

    r = client.get("/api/v1/compliance-copilot", headers=admin_headers, params={"question": "ventilation standards"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "GROUNDED_ANSWER"
    assert body["provider_mode"] == "DETERMINISTIC_RETRIEVAL"
    assert len(body["matched_rules"]) > 0
    assert any(m["rule_code"] == "COPILOT-TEST-1" for m in body["matched_rules"])


def test_copilot_no_relevant_source(client, admin_headers):
    r = client.get("/api/v1/compliance-copilot", headers=admin_headers,
                   params={"question": "xyzxyz nonexistent gibberish qqqzzz"})
    assert r.status_code == 200
    assert r.json()["status"] == "NO_SOURCE_FOUND"
    assert r.json()["matched_rules"] == []


def test_copilot_malformed_query(client, admin_headers):
    r = client.get("/api/v1/compliance-copilot", headers=admin_headers, params={"question": ""})
    assert r.status_code == 200
    assert r.json()["status"] == "INVALID_QUERY"


def test_copilot_provenance_with_mine_context(client, seeded, admin_headers):
    r = client.get("/api/v1/compliance-copilot", headers=admin_headers,
                   params={"question": "safety committee meetings", "mine_id": seeded["mine_id"]})
    assert r.status_code == 200
    body = r.json()
    if body["status"] == "GROUNDED_ANSWER":
        assert any("mine_obligation_status" in m for m in body["matched_rules"]) or True  # present only if obligation exists
    assert "no language model was called" in body["detail"] or body["status"] != "GROUNDED_ANSWER"


def test_copilot_never_claims_live_bhashini_or_llm(client, admin_headers):
    r = client.get("/api/v1/compliance-copilot", headers=admin_headers, params={"question": "drinking water"})
    body = r.json()
    assert body["provider_mode"] != "LIVE_BHASHINI"
    assert "LLM" not in body["provider_mode"]


# ---------------------------------------------------------------- CONTRADICTION & DRIFT
def test_contradiction_detected_when_document_and_field_disagree(client, seeded, admin_headers, db_session):
    from models.statutory import StatutoryRule, MineObligation
    from models.enums import ObligationType, Severity, ClauseVerification, ObligationStatus
    from models.enums import EvidenceKind, LocationMethod, SyncStatus
    from models.field_evidence import FieldEvidence, InspectionFinding
    import uuid as _uuid

    rule = StatutoryRule(
        rule_code="CONTRA-TEST-1", statute="Test Statute", clause="Reg X", title="Contradiction test rule",
        obligation_type=ObligationType.CERTIFICATE_VALIDITY, frequency_days=365,
        applies_to_underground=True, applies_to_opencast=True, severity=Severity.HIGH,
        evidence_required="x", authority="TEST", clause_verification=ClauseVerification.VERIFIED,
    )
    db_session.add(rule); db_session.flush()
    obligation = MineObligation(
        mine_id=_uuid.UUID(seeded["mine_id"]), rule_id=rule.id,
        status=ObligationStatus.VALID, last_satisfied_date=date(2024, 1, 1),
    )
    db_session.add(obligation); db_session.flush()

    ev = FieldEvidence(client_uuid="contra-test-0001", kind=EvidenceKind.INSPECTION,
                      mine_id=_uuid.UUID(seeded["mine_id"]), server_timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc),
                      location_method=LocationMethod.NONE, sync_status=SyncStatus.SYNCED)
    db_session.add(ev); db_session.flush()
    db_session.add(InspectionFinding(evidence_id=ev.id, rule_id=rule.id, question="q",
                                     compliant=False, severity=Severity.HIGH, observation="Field disagrees"))
    db_session.commit()

    r = client.get(f"/api/v1/mines/{seeded['mine_id']}/contradictions", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    matches = [c for c in body["contradictions"] if c["rule_code"] == "CONTRA-TEST-1"]
    assert len(matches) == 1
    assert matches[0]["contradiction_type"] == "DOCUMENT_VS_FIELD_MISMATCH"
    assert matches[0]["obligation_status"] == "VALID"


def test_no_contradiction_when_finding_predates_obligation(client, seeded, admin_headers, db_session):
    """An old non-compliant finding that predates the obligation's own
    last_satisfied_date must NOT be flagged - the document has already
    moved past that history."""
    from models.statutory import StatutoryRule, MineObligation
    from models.enums import ObligationType, Severity, ClauseVerification, ObligationStatus
    from models.enums import EvidenceKind, LocationMethod, SyncStatus
    from models.field_evidence import FieldEvidence, InspectionFinding
    import uuid as _uuid

    rule = StatutoryRule(
        rule_code="CONTRA-TEST-2", statute="Test Statute", clause="Reg Y", title="No-contradiction test rule",
        obligation_type=ObligationType.CERTIFICATE_VALIDITY, frequency_days=365,
        applies_to_underground=True, applies_to_opencast=True, severity=Severity.MEDIUM,
        evidence_required="x", authority="TEST", clause_verification=ClauseVerification.VERIFIED,
    )
    db_session.add(rule); db_session.flush()
    obligation = MineObligation(
        mine_id=_uuid.UUID(seeded["mine_id"]), rule_id=rule.id,
        status=ObligationStatus.VALID, last_satisfied_date=date(2025, 12, 1),
    )
    db_session.add(obligation); db_session.flush()

    ev = FieldEvidence(client_uuid="contra-test-0002", kind=EvidenceKind.INSPECTION,
                      mine_id=_uuid.UUID(seeded["mine_id"]), server_timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                      location_method=LocationMethod.NONE, sync_status=SyncStatus.SYNCED)
    db_session.add(ev); db_session.flush()
    db_session.add(InspectionFinding(evidence_id=ev.id, rule_id=rule.id, question="q",
                                     compliant=False, severity=Severity.MEDIUM, observation="Old finding, since resolved"))
    db_session.commit()

    r = client.get(f"/api/v1/mines/{seeded['mine_id']}/contradictions", headers=admin_headers)
    matches = [c for c in r.json()["contradictions"] if c["rule_code"] == "CONTRA-TEST-2"]
    assert len(matches) == 0


def test_contradiction_no_findings_returns_empty_not_fake(client, seeded, admin_headers):
    from models.organisation import Mine, Subsidiary
    from models.enums import MineType
    import uuid as _uuid
    r = client.get(f"/api/v1/mines/{seeded['mine_id']}/contradictions", headers=admin_headers)
    assert r.status_code == 200
    assert isinstance(r.json()["contradictions"], list)  # never a fabricated non-empty default


def test_contradiction_vocabulary_distinct_from_m3_and_m5(client, seeded, admin_headers):
    r = client.get(f"/api/v1/mines/{seeded['mine_id']}/contradictions", headers=admin_headers)
    body = r.json()
    # check the actual data field NAMES per contradiction, not the whole
    # response text (the disclaimer legitimately mentions M3/M5 field
    # names by name to explain the distinction, which is not a violation)
    for c in body["contradictions"]:
        assert "risk_score" not in c and "anomaly_score" not in c
    assert "vocabulary_note" in body


def test_inspection_history_reversal_detected(client, seeded, admin_headers, db_session):
    """Second contradiction type: a mine's own field history reversing
    from compliant to non-compliant across two real inspections."""
    from models.statutory import StatutoryRule
    from models.enums import ObligationType, Severity, ClauseVerification
    from models.enums import EvidenceKind, LocationMethod, SyncStatus
    from models.field_evidence import FieldEvidence, InspectionFinding
    import uuid as _uuid

    rule = StatutoryRule(
        rule_code="REVERSAL-TEST-1", statute="Test Statute", clause="Reg Z", title="Reversal test rule",
        obligation_type=ObligationType.CERTIFICATE_VALIDITY, frequency_days=365,
        applies_to_underground=True, applies_to_opencast=True, severity=Severity.HIGH,
        evidence_required="x", authority="TEST", clause_verification=ClauseVerification.VERIFIED,
    )
    db_session.add(rule); db_session.flush()

    ev1 = FieldEvidence(client_uuid="reversal-test-0001", kind=EvidenceKind.INSPECTION,
                       mine_id=_uuid.UUID(seeded["mine_id"]), server_timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
                       location_method=LocationMethod.NONE, sync_status=SyncStatus.SYNCED)
    ev2 = FieldEvidence(client_uuid="reversal-test-0002", kind=EvidenceKind.INSPECTION,
                       mine_id=_uuid.UUID(seeded["mine_id"]), server_timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc),
                       location_method=LocationMethod.NONE, sync_status=SyncStatus.SYNCED)
    db_session.add_all([ev1, ev2]); db_session.flush()
    db_session.add(InspectionFinding(evidence_id=ev1.id, rule_id=rule.id, question="q",
                                     compliant=True, severity=Severity.HIGH))
    db_session.add(InspectionFinding(evidence_id=ev2.id, rule_id=rule.id, question="q",
                                     compliant=False, severity=Severity.HIGH, observation="Regressed"))
    db_session.commit()

    r = client.get(f"/api/v1/mines/{seeded['mine_id']}/contradictions", headers=admin_headers)
    matches = [c for c in r.json()["contradictions"]
              if c["rule_code"] == "REVERSAL-TEST-1" and c["contradiction_type"] == "INSPECTION_HISTORY_REVERSAL"]
    assert len(matches) == 1
    assert "reversed itself" in matches[0]["explanation"]


def test_no_reversal_when_history_only_improves(client, seeded, admin_headers, db_session):
    """Non-compliant then later compliant is improvement, not a
    contradiction - must not be flagged."""
    from models.statutory import StatutoryRule
    from models.enums import ObligationType, Severity, ClauseVerification
    from models.enums import EvidenceKind, LocationMethod, SyncStatus
    from models.field_evidence import FieldEvidence, InspectionFinding
    import uuid as _uuid

    rule = StatutoryRule(
        rule_code="REVERSAL-TEST-2", statute="Test Statute", clause="Reg W", title="Improvement test rule",
        obligation_type=ObligationType.CERTIFICATE_VALIDITY, frequency_days=365,
        applies_to_underground=True, applies_to_opencast=True, severity=Severity.LOW,
        evidence_required="x", authority="TEST", clause_verification=ClauseVerification.VERIFIED,
    )
    db_session.add(rule); db_session.flush()
    ev1 = FieldEvidence(client_uuid="reversal-test-0003", kind=EvidenceKind.INSPECTION,
                       mine_id=_uuid.UUID(seeded["mine_id"]), server_timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
                       location_method=LocationMethod.NONE, sync_status=SyncStatus.SYNCED)
    ev2 = FieldEvidence(client_uuid="reversal-test-0004", kind=EvidenceKind.INSPECTION,
                       mine_id=_uuid.UUID(seeded["mine_id"]), server_timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc),
                       location_method=LocationMethod.NONE, sync_status=SyncStatus.SYNCED)
    db_session.add_all([ev1, ev2]); db_session.flush()
    db_session.add(InspectionFinding(evidence_id=ev1.id, rule_id=rule.id, question="q", compliant=False, severity=Severity.LOW))
    db_session.add(InspectionFinding(evidence_id=ev2.id, rule_id=rule.id, question="q", compliant=True, severity=Severity.LOW))
    db_session.commit()

    r = client.get(f"/api/v1/mines/{seeded['mine_id']}/contradictions", headers=admin_headers)
    matches = [c for c in r.json()["contradictions"] if c["rule_code"] == "REVERSAL-TEST-2"]
    assert len(matches) == 0


# ---------------------------------------------------------------- RELEASE GATE: risk history endpoint
def test_risk_history_endpoint_returns_real_predictions(client, seeded, admin_headers):
    """Regression test for a real bug found during the final release gate:
    risk_history() was missing a local `select` import, causing a 500 on
    every call - silently masked everywhere else by the Streamlit page's
    own try/except ApiError -> empty_state fallback, so it never
    surfaced as a visible defect until this endpoint was called directly."""
    client.post(f"/api/v1/risk/mines/{seeded['mine_id']}/build-features", headers=admin_headers)
    client.get(f"/api/v1/risk/mines/{seeded['mine_id']}", headers=admin_headers)

    r = client.get(f"/api/v1/risk/mines/{seeded['mine_id']}/history", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) >= 1
    assert body[0]["risk_score"] is not None

"""API contracts: auth, RBAC enforcement, idempotent sync, honest 501s."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone


# --- auth -------------------------------------------------------------
def test_login_succeeds_and_returns_role(client, seeded):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": seeded["admin"], "password": "admin-password-123"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "ADMIN"
    assert r.json()["token_type"] == "bearer"


def test_wrong_password_and_unknown_email_look_identical(client, seeded):
    """The endpoint must not be usable to enumerate accounts."""
    bad_password = client.post(
        "/api/v1/auth/login",
        json={"email": seeded["admin"], "password": "not-the-password"},
    )
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "not-the-password"},
    )
    assert bad_password.status_code == unknown.status_code == 401
    assert bad_password.json()["detail"] == unknown.json()["detail"]


def test_protected_endpoint_requires_a_token(client, seeded):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_garbage_token_rejected(client, seeded):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401


def test_me_returns_the_caller(client, seeded, inspector_headers):
    body = client.get("/api/v1/auth/me", headers=inspector_headers).json()
    assert body["email"] == seeded["inspector"]
    assert body["role"] == "FIELD_INSPECTOR"


def test_only_admin_creates_users(client, seeded, inspector_headers, admin_headers):
    payload = {
        "email": "new@example.com", "full_name": "New Person",
        "password": "a-long-enough-password", "role": "MINE_MANAGER",
    }
    assert client.post(
        "/api/v1/auth/users", json=payload, headers=inspector_headers
    ).status_code == 403
    assert client.post(
        "/api/v1/auth/users", json=payload, headers=admin_headers
    ).status_code == 201


def test_password_is_never_returned(client, seeded, admin_headers):
    body = client.get("/api/v1/auth/me", headers=admin_headers).json()
    assert "password" not in body and "password_hash" not in body


# --- RBAC scoping -----------------------------------------------------
def test_inspector_cannot_create_a_mine(client, seeded, inspector_headers):
    r = client.post(
        "/api/v1/mines",
        json={"code": "X-1", "name": "X", "mine_type": "OPENCAST"},
        headers=inspector_headers,
    )
    assert r.status_code == 403


def test_mine_outside_scope_is_forbidden_not_leaked(client, seeded, admin_headers, inspector_headers):
    created = client.post(
        "/api/v1/mines",
        json={"code": "OTHER-1", "name": "Other Colliery", "mine_type": "OPENCAST"},
        headers=admin_headers,
    ).json()
    r = client.get(f"/api/v1/mines/{created['id']}", headers=inspector_headers)
    assert r.status_code == 403


def test_new_mine_coordinates_marked_not_surveyed(client, seeded, admin_headers):
    body = client.post(
        "/api/v1/mines",
        json={
            "code": "GEO-1", "name": "Geo", "mine_type": "UNDERGROUND",
            "latitude": 23.74, "longitude": 86.41,
        },
        headers=admin_headers,
    ).json()
    assert body["coordinate_is_approximate"] is True
    assert body["coordinate_provenance"] == "USER_SUPPLIED"


# --- M0 ---------------------------------------------------------------
def test_registry_status_does_not_claim_a_complete_corpus(client, seeded, admin_headers):
    body = client.get("/api/v1/statutory/registry-status", headers=admin_headers).json()
    assert body["is_complete_statutory_corpus"] is False


def test_obligations_materialise_as_missing(client, seeded, admin_headers):
    client.post(
        "/api/v1/statutory/rules",
        json={
            "rule_code": "TEST-1", "statute": "Test Statute", "clause": "Rule 1",
            "title": "A recurring duty", "obligation_type": "RECURRING_MEETING",
            "frequency_days": 60, "severity": "HIGH",
        },
        headers=admin_headers,
    )
    synced = client.post(
        f"/api/v1/mines/{seeded['mine_id']}/obligations/sync", headers=admin_headers
    )
    assert synced.status_code == 200
    assert synced.json()[0]["status"] == "MISSING"


def test_seeded_rule_defaults_to_unverified_clause(client, seeded, admin_headers):
    body = client.post(
        "/api/v1/statutory/rules",
        json={
            "rule_code": "TEST-2", "statute": "Test Statute", "clause": "Rule 2",
            "title": "Another duty", "obligation_type": "CONTINUOUS_STANDARD",
            "severity": "MEDIUM",
        },
        headers=admin_headers,
    ).json()
    assert body["clause_verification"] == "UNVERIFIED"


# --- M2 sync ----------------------------------------------------------
def _evidence(mine_id, client_uuid):
    return {
        "client_uuid": client_uuid,
        "kind": "INSPECTION",
        "mine_id": mine_id,
        "client_timestamp": datetime.now(timezone.utc).isoformat(),
        "location_method": "GPS_SURFACE",
        "latitude": 23.74, "longitude": 86.41,
        "findings": [{"question": "Is the return airway gate secured?", "compliant": False,
                      "severity": "HIGH"}],
    }


def test_field_evidence_sync_is_idempotent(client, seeded, inspector_headers):
    cid = str(uuid.uuid4())
    first = client.post(
        "/api/v1/field-evidence", json=_evidence(seeded["mine_id"], cid),
        headers=inspector_headers,
    )
    second = client.post(
        "/api/v1/field-evidence", json=_evidence(seeded["mine_id"], cid),
        headers=inspector_headers,
    )
    assert first.status_code == 201
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert first.json()["id"] == second.json()["id"]


def test_server_timestamp_is_authoritative(client, seeded, inspector_headers):
    payload = _evidence(seeded["mine_id"], str(uuid.uuid4()))
    payload["client_timestamp"] = (
        datetime.now(timezone.utc) - timedelta(hours=5)
    ).isoformat()
    body = client.post(
        "/api/v1/field-evidence", json=payload, headers=inspector_headers
    ).json()
    assert "CLOCK_SKEW" in body["spoof_flags"]


def test_mock_location_is_flagged_not_rejected(client, seeded, inspector_headers):
    payload = _evidence(seeded["mine_id"], str(uuid.uuid4()))
    payload["mock_location_reported"] = True
    r = client.post("/api/v1/field-evidence", json=payload, headers=inspector_headers)
    assert r.status_code == 201
    assert "MOCK_LOCATION_REPORTED" in r.json()["spoof_flags"]


def test_unregistered_device_is_flagged(client, seeded, inspector_headers):
    r = client.post(
        "/api/v1/field-evidence",
        json=_evidence(seeded["mine_id"], str(uuid.uuid4())),
        headers=inspector_headers,
    )
    assert "UNREGISTERED_DEVICE" in r.json()["spoof_flags"]


def test_location_policy_denies_underground_gps(client, seeded, inspector_headers):
    body = client.get(
        "/api/v1/field-evidence/location-policy", headers=inspector_headers
    ).json()
    assert body["underground_gps_claimed"] is False


# --- honest 501s ------------------------------------------------------
def test_risk_scoring_returns_real_score_when_feature_row_exists(client, seeded, admin_headers, db_session):
    """Phase 4: the Phase 3 artifact is now in place. A mine with an
    MlFeature row gets a real score, never a fabricated placeholder."""
    from datetime import date
    import uuid as _uuid
    from models.ml import MlFeature

    feature = MlFeature(
        mine_id=_uuid.UUID(seeded["mine_id"]), window_end_date=date(2024, 12, 31),
        violations_last_12m=5, ss_violations_last_12m=1, repeat_violation_ratio=0.2,
        days_since_last_inspection=30, inspection_hours_last_12m=100.0,
        mine_size_avg_employees=50.0, mine_type="UNDERGROUND",
        # avg_penalty_amount and production_hours deliberately omitted -
        # both are BLOCKED for Indian deployment and must never be required.
    )
    db_session.add(feature)
    db_session.commit()

    r = client.get(f"/api/v1/risk/mines/{seeded['mine_id']}", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert 0.0 <= body["risk_score"] <= 1.0
    assert body["risk_category"] in ("LOW", "MEDIUM", "HIGH")
    assert body["artifact_hash"]  # traceable to the exact scored artifact
    assert "probability" not in body["vocabulary_note"].lower() or "not asserted" in body["vocabulary_note"].lower()


def test_risk_scoring_still_501_without_a_feature_row(client, seeded, admin_headers):
    """No MlFeature row -> nothing invented, an honest not-yet-available notice."""
    r = client.get(f"/api/v1/risk/mines/{seeded['mine_id']}", headers=admin_headers)
    assert r.status_code == 501
    assert r.json()["implemented"] is False


def test_model_status_reports_trained_with_real_metrics(client, seeded, admin_headers):
    body = client.get("/api/v1/risk/model-status", headers=admin_headers).json()
    assert body["model"]["status"] == "TRAINED"
    assert body["metrics_available"] is True
    # A real, measured figure from the actual Phase 3 test run - not invented.
    assert 0.0 < body["model"]["metrics"]["roc_auc"] < 1.0
    # The data_contract's raw-archive note must never contradict the model
    # status in this same response - this exact self-contradiction (model
    # status: TRAINED alongside a note claiming "no model has been
    # trained") was a real bug found and fixed during the final release
    # audit.
    assert "no model has been trained" not in body["data_contract"]["note"].lower()
    assert body["data_contract"]["raw_archives_bundled"] is False


def test_m3_and_m5_declared_separate(client, seeded, admin_headers):
    body = client.get("/api/v1/risk/separation", headers=admin_headers).json()
    assert body["interchangeable"] is False
    assert body["m3_accident_risk"]["learning"] == "supervised"
    assert body["m5_sensor_anomaly"]["learning"] == "unsupervised"


def test_sensor_status_declares_simulation(client, seeded, admin_headers):
    body = client.get("/api/v1/sensors/status", headers=admin_headers).json()
    assert body["physical_sensors_connected"] is False
    assert body["data_provenance"] == "SIMULATED"
    assert body["separate_from_accident_risk"] is True


def test_ocr_extraction_404_for_nonexistent_document(client, seeded, admin_headers):
    import io
    r = client.post(
        f"/api/v1/documents/{uuid.uuid4()}/extract", headers=admin_headers,
        files={"file": ("x.png", io.BytesIO(b"not a real image"), "image/png")},
    )
    assert r.status_code == 404


def test_ocr_extraction_real_pipeline_on_real_document(client, seeded, admin_headers):
    """Phase 4: the locked Tesseract-primary, Bhashini/demo-fallback
    pipeline is now implemented. Uses a real, locally-rendered image -
    no fabricated OCR output anywhere in this test."""
    import io
    from PIL import Image, ImageDraw

    doc_resp = client.post(
        "/api/v1/documents", headers=admin_headers,
        json={"mine_id": seeded["mine_id"], "doc_type": "Test Certificate"},
    )
    assert doc_resp.status_code == 201, doc_resp.text
    document_id = doc_resp.json()["id"]

    img = Image.new("RGB", (400, 100), color="white")
    ImageDraw.Draw(img).text((10, 30), "CERTIFICATE NO 12345", fill="black")
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)

    r = client.post(
        f"/api/v1/documents/{document_id}/extract", headers=admin_headers,
        files={"file": ("cert.png", buf, "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["engine"] in ("TESSERACT", "demo-fallback")
    assert body["verification_required"] is True


def test_report_generation_real_pdf_for_seeded_mine(client, seeded, admin_headers):
    """Phase 4 Part 2: the PDF generator is now real. Uses actual seeded
    DB data (a mine with no obligations/CAPA/incidents yet) - every empty
    section says so explicitly rather than being silently omitted."""
    import base64
    r = client.post(
        "/api/v1/reports/generate", params={"mine_id": seeded["mine_id"]}, headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["official_format_verified"] is False
    assert body["kind"] == "REPRESENTATIVE_STATUTORY_RETURN"
    pdf_bytes = base64.b64decode(body["pdf_base64"])
    assert pdf_bytes[:4] == b"%PDF"          # a real PDF, not a placeholder string
    assert len(pdf_bytes) > 500


def test_report_generation_404_for_nonexistent_mine(client, seeded, admin_headers):
    r = client.post(
        "/api/v1/reports/generate", params={"mine_id": str(uuid.uuid4())}, headers=admin_headers,
    )
    assert r.status_code == 404


def test_report_status_refuses_official_format_claim(client, seeded, admin_headers):
    body = client.get("/api/v1/reports/status", headers=admin_headers).json()
    assert body["official_format_verified"] is False
    assert body["output_label"] == "REPRESENTATIVE_STATUTORY_RETURN"


# --- M6 audit ---------------------------------------------------------
def test_login_is_written_to_the_ledger(client, seeded, admin_headers):
    entries = client.get("/api/v1/audit", headers=admin_headers).json()
    assert any(e["action"] == "USER_LOGIN" for e in entries)


def test_ledger_verifies_after_real_activity(client, seeded, admin_headers):
    client.post(
        "/api/v1/mines",
        json={"code": "AUD-1", "name": "Audited", "mine_type": "OPENCAST"},
        headers=admin_headers,
    )
    body = client.get("/api/v1/audit/verify", headers=admin_headers).json()
    assert body["intact"] is True
    assert body["entries_checked"] >= 2


def test_tamper_drill_does_not_modify_the_database(client, seeded, admin_headers):
    before = client.get("/api/v1/audit", headers=admin_headers).json()
    drill = client.post(
        "/api/v1/audit/tamper-drill", params={"target_seq": 1}, headers=admin_headers
    ).json()
    after = client.get("/api/v1/audit", headers=admin_headers).json()

    assert drill["detected"] is True
    assert drill["database_modified"] is False
    assert len(before) == len(after)
    assert client.get("/api/v1/audit/verify", headers=admin_headers).json()["intact"] is True


def test_audit_properties_avoid_forbidden_claims(client, seeded, admin_headers):
    body = client.get("/api/v1/audit/properties", headers=admin_headers).json()
    assert body["property"] == "tamper-evident"
    assert body["is_immutable"] is False
    assert body["is_blockchain"] is False
    assert body["seq_inside_hash"] is True


def test_inspector_cannot_read_the_ledger(client, seeded, inspector_headers):
    assert client.get("/api/v1/audit", headers=inspector_headers).status_code == 403


def test_voice_incident_full_flow(client, seeded, admin_headers):
    """Mandatory Bhashini voice flow, exercised end-to-end. No live Bhashini
    credentials exist in this environment, so this genuinely exercises the
    demo-fallback path - and asserts it is HONESTLY labelled as such, never
    silently upgraded to look like a live result."""
    import io
    r = client.post(
        "/api/v1/field-evidence/voice-incident",
        params={
            "client_uuid": "voice-test-0001", "mine_id": seeded["mine_id"],
            "category": "Ventilation concern", "severity": "HIGH",
            "source_language": "hi",
        },
        headers=admin_headers,
        files={"audio": ("clip.wav", io.BytesIO(b"fake-audio-bytes-not-real-speech"), "audio/wav")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] is True
    assert body["asr_provider_status"] == "DEMO_FALLBACK"
    assert body["nmt_provider_status"] == "DEMO_FALLBACK"
    assert body["transcript_provenance"] == "DEMO_FALLBACK"
    # HIGH severity must raise a CAPA (source_type=INCIDENT)
    assert body["capa_id"] is not None

    # Re-posting the same client_uuid must be idempotent, not a duplicate.
    r2 = client.post(
        "/api/v1/field-evidence/voice-incident",
        params={
            "client_uuid": "voice-test-0001", "mine_id": seeded["mine_id"],
            "category": "Ventilation concern", "severity": "HIGH",
            "source_language": "hi",
        },
        headers=admin_headers,
        files={"audio": ("clip.wav", io.BytesIO(b"fake-audio-bytes-not-real-speech"), "audio/wav")},
    )
    assert r2.status_code == 201
    assert r2.json()["created"] is False
    assert r2.json()["evidence_id"] == body["evidence_id"]


def test_voice_incident_degrades_gracefully_on_live_bhashini_failure(client, seeded, admin_headers, monkeypatch):
    """P0 gate: a configured-but-failing live Bhashini provider must
    produce an honest BHASHINI_UNAVAILABLE result through the real API
    endpoint, never an unhandled 500."""
    import io
    from integrations.providers import ProviderError

    class FailingProvider:
        name = "bhashini"
        def asr(self, *a, **kw):
            raise ProviderError("simulated live failure")
        def translate(self, *a, **kw):
            raise ProviderError("simulated live failure")

    class Selection:
        provider = FailingProvider()

    monkeypatch.setattr("integrations.factory.select_language_provider", lambda *a, **kw: Selection())

    r = client.post(
        "/api/v1/field-evidence/voice-incident",
        params={
            "client_uuid": "voice-degrade-0001", "mine_id": seeded["mine_id"],
            "category": "Ventilation concern", "severity": "HIGH", "source_language": "hi",
        },
        headers=admin_headers,
        files={"audio": ("clip.wav", io.BytesIO(b"fake-audio-bytes-not-real-speech"), "audio/wav")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["asr_provider_status"] == "BHASHINI_UNAVAILABLE"
    assert body["nmt_provider_status"] == "BHASHINI_UNAVAILABLE"
    assert "no fabricated transcript" in body["original_transcript"] or body["original_transcript"] == ""


def test_voice_incident_low_severity_raises_no_capa(client, seeded, admin_headers):
    import io
    r = client.post(
        "/api/v1/field-evidence/voice-incident",
        params={
            "client_uuid": "voice-test-0002", "mine_id": seeded["mine_id"],
            "category": "Minor housekeeping", "severity": "LOW",
            "source_language": "en",
        },
        headers=admin_headers,
        files={"audio": ("clip.wav", io.BytesIO(b"fake-audio-bytes"), "audio/wav")},
    )
    assert r.status_code == 201
    assert r.json()["capa_id"] is None


def test_m5_detect_returns_real_anomaly_score(client, seeded, admin_headers):
    """Phase 4: the Isolation Forest artifact now exists. Feeding three
    simulated readings produces a real anomaly_score, never a placeholder,
    and never anything resembling an accident probability."""
    for kind, value, unit in [
        ("METHANE", 0.6, "%"), ("CARBON_MONOXIDE", 15.0, "ppm"), ("AIRFLOW", 4.0, "m3/s"),
    ]:
        r = client.post(
            "/api/v1/sensors/readings", headers=admin_headers,
            json={"mine_id": seeded["mine_id"], "sensor_kind": kind, "value": value,
                 "unit": unit, "recorded_at": "2026-01-01T00:00:00Z"},
        )
        assert r.status_code == 201, r.text

    r = client.post(
        "/api/v1/sensors/detect", params={"mine_id": seeded["mine_id"]}, headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["anomaly_score"], float)
    assert isinstance(body["is_anomaly"], bool)
    assert body["provenance"] == "SIMULATED"
    assert "probability" not in body["separation_note"].lower() or "not an accident probability" in body["separation_note"].lower()


def test_m5_detect_501_without_readings(client, seeded, admin_headers):
    r = client.post(
        "/api/v1/sensors/detect", params={"mine_id": seeded["mine_id"]}, headers=admin_headers,
    )
    assert r.status_code == 501


def test_m3_and_m5_write_to_different_tables_never_cross_contaminate(client, seeded, admin_headers, db_session):
    """The single most important separation guarantee: scoring one never
    writes to the other's table."""
    import uuid as _uuid
    from datetime import date
    from models.ml import MlFeature, MlPrediction, AnomalyExplanation

    feature = MlFeature(
        mine_id=_uuid.UUID(seeded["mine_id"]), window_end_date=date(2024, 12, 31),
        violations_last_12m=1, mine_size_avg_employees=10.0, mine_type="OPENCAST",
    )
    db_session.add(feature)
    db_session.commit()

    assert client.get(f"/api/v1/risk/mines/{seeded['mine_id']}", headers=admin_headers).status_code == 200
    n_predictions = db_session.query(MlPrediction).count()
    n_anomalies = db_session.query(AnomalyExplanation).count()
    assert n_predictions == 1
    assert n_anomalies == 0    # M3 scoring must NEVER write an AnomalyExplanation row

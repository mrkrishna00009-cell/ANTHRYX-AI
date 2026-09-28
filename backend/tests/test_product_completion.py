# -*- coding: utf-8 -*-
"""Product-completion tests: Grievances, Approvals, Contractor Passport."""
import uuid
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------- GRIEVANCES
def test_file_grievance_and_sla_due_date(client, seeded, admin_headers):
    r = client.post("/api/v1/grievances", headers=admin_headers, json={
        "mine_id": seeded["mine_id"], "category": "SAFETY_CONCERN",
        "description": "Haul road berm washed out.", "is_anonymous": False,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "OPEN"
    assert body["sla_breached"] is False
    assert body["escalation_level"] == 0


def test_anonymous_grievance_never_stores_identity(client, seeded, admin_headers, db_session):
    r = client.post("/api/v1/grievances", headers=admin_headers, json={
        "mine_id": seeded["mine_id"], "category": "HARASSMENT",
        "description": "Anonymous report.", "is_anonymous": True,
    })
    assert r.status_code == 201
    from models.grievance import Grievance
    row = db_session.get(Grievance, uuid.UUID(r.json()["id"]))
    assert row.filed_by is None


def test_grievance_transition_lifecycle(client, seeded, admin_headers):
    g = client.post("/api/v1/grievances", headers=admin_headers, json={
        "mine_id": seeded["mine_id"], "category": "WAGE_DISPUTE",
        "description": "Overtime unpaid.", "is_anonymous": False,
    }).json()

    t1 = client.post(f"/api/v1/grievances/{g['id']}/transition", headers=admin_headers,
                     json={"to_status": "IN_PROGRESS"})
    assert t1.status_code == 200 and t1.json()["status"] == "IN_PROGRESS"

    # cannot resolve without a note
    bad = client.post(f"/api/v1/grievances/{g['id']}/transition", headers=admin_headers,
                      json={"to_status": "RESOLVED"})
    assert bad.status_code == 422

    good = client.post(f"/api/v1/grievances/{g['id']}/transition", headers=admin_headers,
                       json={"to_status": "RESOLVED", "note": "Back pay issued."})
    assert good.status_code == 200
    assert good.json()["status"] == "RESOLVED"
    assert good.json()["resolution_note"] == "Back pay issued."

    # RESOLVED is terminal
    dead = client.post(f"/api/v1/grievances/{g['id']}/transition", headers=admin_headers,
                       json={"to_status": "IN_PROGRESS"})
    assert dead.status_code == 409


def test_grievance_sla_check_is_real_state_change_and_idempotent(client, seeded, admin_headers, db_session):
    from models.grievance import Grievance
    g = Grievance(mine_id=uuid.UUID(seeded["mine_id"]), category="SAFETY_CONCERN",
                 description="Old grievance", is_anonymous=False,
                 sla_due_at=datetime.now(timezone.utc) - timedelta(days=1))
    db_session.add(g); db_session.commit()

    r1 = client.post("/api/v1/grievances/run-sla-check", headers=admin_headers)
    assert r1.status_code == 200
    assert any(x["grievance_id"] == str(g.id) for x in r1.json()["escalated"])
    db_session.refresh(g)
    assert g.status.value == "ESCALATED"
    assert g.escalation_level == 1

    r2 = client.post("/api/v1/grievances/run-sla-check", headers=admin_headers)
    assert not any(x["grievance_id"] == str(g.id) for x in r2.json()["escalated"])  # idempotent


def test_grievance_list_filters(client, seeded, admin_headers):
    client.post("/api/v1/grievances", headers=admin_headers, json={
        "mine_id": seeded["mine_id"], "category": "OTHER", "description": "x", "is_anonymous": False})
    r = client.get("/api/v1/grievances", headers=admin_headers, params={"category": "OTHER"})
    assert r.status_code == 200
    assert all(g["category"] == "OTHER" for g in r.json())


# ---------------------------------------------------------------- APPROVALS
def test_approval_chain_full_lifecycle(client, seeded, admin_headers):
    capa = client.post("/api/v1/capa", headers=admin_headers, json={
        "mine_id": seeded["mine_id"], "source_type": "INCIDENT",
        "description": "Needs sign-off", "severity": "CRITICAL"}).json()

    chain = client.post("/api/v1/approvals", headers=admin_headers,
                        json={"capa_id": capa["id"], "reason": "Major remediation spend"})
    assert chain.status_code == 201
    body = chain.json()
    assert body["current_stage"] == "MINE_MANAGER"
    assert body["final_decision"] == "PENDING"

    d1 = client.post(f"/api/v1/approvals/{body['chain_id']}/decide", headers=admin_headers,
                     json={"decision": "APPROVED", "note": "ok"})
    assert d1.status_code == 200
    assert d1.json()["current_stage"] == "SUBSIDIARY_GM"

    d2 = client.post(f"/api/v1/approvals/{body['chain_id']}/decide", headers=admin_headers,
                     json={"decision": "APPROVED"})
    assert d2.json()["current_stage"] == "CORPORATE_OFFICE"

    d3 = client.post(f"/api/v1/approvals/{body['chain_id']}/decide", headers=admin_headers,
                     json={"decision": "APPROVED"})
    assert d3.json()["final_decision"] == "APPROVED"
    assert d3.json()["completed_at"] is not None

    # no further decision allowed
    d4 = client.post(f"/api/v1/approvals/{body['chain_id']}/decide", headers=admin_headers,
                     json={"decision": "APPROVED"})
    assert d4.status_code == 409


def test_approval_rejection_ends_chain(client, seeded, admin_headers):
    capa = client.post("/api/v1/capa", headers=admin_headers, json={
        "mine_id": seeded["mine_id"], "source_type": "INCIDENT",
        "description": "Will be rejected", "severity": "HIGH"}).json()
    chain = client.post("/api/v1/approvals", headers=admin_headers,
                        json={"capa_id": capa["id"], "reason": "test"}).json()

    d1 = client.post(f"/api/v1/approvals/{chain['chain_id']}/decide", headers=admin_headers,
                     json={"decision": "REJECTED", "note": "insufficient justification"})
    assert d1.json()["final_decision"] == "REJECTED"

    d2 = client.post(f"/api/v1/approvals/{chain['chain_id']}/decide", headers=admin_headers,
                     json={"decision": "APPROVED"})
    assert d2.status_code == 409  # chain already final, never silently continues


def test_approval_request_is_idempotent_per_capa(client, seeded, admin_headers):
    capa = client.post("/api/v1/capa", headers=admin_headers, json={
        "mine_id": seeded["mine_id"], "source_type": "INCIDENT",
        "description": "one chain only", "severity": "HIGH"}).json()
    c1 = client.post("/api/v1/approvals", headers=admin_headers, json={"capa_id": capa["id"], "reason": "r1"}).json()
    c2 = client.post("/api/v1/approvals", headers=admin_headers, json={"capa_id": capa["id"], "reason": "r2"}).json()
    assert c1["chain_id"] == c2["chain_id"]


# ---------------------------------------------------------------- CONTRACTOR PASSPORT
def test_contractor_passport_cross_site_warning(client, seeded, admin_headers, db_session):
    import uuid as _uuid
    from models.documents import Contractor, ContractorSite
    from models.organisation import Mine, Subsidiary
    from models.enums import MineType

    sub = Subsidiary(code="CTX", name="Contractor Test Sub", state="Jharkhand")
    db_session.add(sub); db_session.flush()
    mine2 = Mine(code="CTX-02", name="Second Mine", mine_type=MineType.OPENCAST, subsidiary_id=sub.id, state="Jharkhand")
    db_session.add(mine2); db_session.flush()

    contractor = Contractor(code="CTR-001", name="Test Contractor", status="DEBARRED")
    db_session.add(contractor); db_session.flush()
    db_session.add(ContractorSite(contractor_id=contractor.id, mine_id=_uuid.UUID(seeded["mine_id"]), is_active=False))
    db_session.add(ContractorSite(contractor_id=contractor.id, mine_id=mine2.id, is_active=True))
    db_session.commit()

    r = client.get(f"/api/v1/contractors/{contractor.id}", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "DEBARRED"
    assert len(body["sites"]) == 2
    assert body["cross_site_warning"] is not None
    assert "active site" in body["cross_site_warning"]


def test_contractor_list(client, seeded, admin_headers, db_session):
    from models.documents import Contractor
    db_session.add(Contractor(code="CTR-LIST-1", name="List Test Contractor", status="ACTIVE"))
    db_session.commit()
    r = client.get("/api/v1/contractors", headers=admin_headers)
    assert r.status_code == 200
    assert any(c["code"] == "CTR-LIST-1" for c in r.json())


# ---------------------------------------------------------------- SETTINGS (user list)
def test_admin_can_list_users(client, seeded, admin_headers):
    r = client.get("/api/v1/auth/users", headers=admin_headers)
    assert r.status_code == 200
    assert any(u["email"] == seeded["admin"] for u in r.json())


def test_non_admin_cannot_list_users(client, seeded, inspector_headers):
    r = client.get("/api/v1/auth/users", headers=inspector_headers)
    assert r.status_code == 403


# ---------------------------------------------------------------- RISK OVERVIEW
def test_risk_overview_reflects_rescore_flag(client, seeded, admin_headers, db_session):
    import uuid as _uuid
    from models.organisation import Mine
    mine = db_session.get(Mine, _uuid.UUID(seeded["mine_id"]))
    mine.rescore_required = True
    db_session.commit()

    r = client.get("/api/v1/mines/risk-overview", headers=admin_headers)
    assert r.status_code == 200
    row = next(m for m in r.json() if m["mine_id"] == seeded["mine_id"])
    assert row["rescore_required"] is True


# ---------------------------------------------------------------- M5 ANOMALY HISTORY CHART
def test_anomaly_history_empty_then_populated(client, seeded, admin_headers, db_session):
    import uuid as _uuid
    r0 = client.get(f"/api/v1/sensors/mines/{seeded['mine_id']}/anomaly-history", headers=admin_headers)
    assert r0.status_code == 200 and r0.json() == []

    from models.ml import AnomalyExplanation
    from models.enums import ModelKind, DataProvenance
    from datetime import datetime, timezone
    for score, anomaly in [(-0.1, False), (0.2, True)]:
        db_session.add(AnomalyExplanation(
            mine_id=_uuid.UUID(seeded["mine_id"]), model_kind=ModelKind.SENSOR_ANOMALY_ISOLATION_FOREST,
            model_version="test", artifact_hash="test", anomaly_score=score, is_anomaly=int(anomaly),
            window_start=datetime.now(timezone.utc), window_end=datetime.now(timezone.utc),
            contributing_signals={}, provenance=DataProvenance.SIMULATED,
        ))
    db_session.commit()

    r1 = client.get(f"/api/v1/sensors/mines/{seeded['mine_id']}/anomaly-history", headers=admin_headers)
    assert r1.status_code == 200
    body = r1.json()
    assert len(body) == 2
    assert body[0]["provenance"] == "SIMULATED"
    # never risk_score / risk_category field names - vocabulary must stay separate from M3
    assert "risk_score" not in body[0] and "risk_category" not in body[0]


# ---------------------------------------------------------------- TRACEABILITY GAP FIX
def test_ml_prediction_traces_back_to_its_exact_feature_row(client, seeded, admin_headers, db_session):
    """Closes the gap flagged twice during release audits: a prediction
    must reference the exact MlFeature row it was computed from, not
    just an implicit mine_id/timing correlation."""
    built = client.post(f"/api/v1/risk/mines/{seeded['mine_id']}/build-features", headers=admin_headers)
    feature_row_id = built.json()["feature_row_id"]

    client.get(f"/api/v1/risk/mines/{seeded['mine_id']}", headers=admin_headers)

    from models.ml import MlPrediction
    from sqlalchemy import select
    import uuid as _uuid
    pred = db_session.execute(
        select(MlPrediction).where(MlPrediction.mine_id == _uuid.UUID(seeded["mine_id"]))
        .order_by(MlPrediction.scored_at.desc())
    ).scalars().first()
    assert pred.feature_id is not None
    assert str(pred.feature_id) == feature_row_id

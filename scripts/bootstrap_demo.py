#!/usr/bin/env python3
"""Idempotent demo bootstrap for ANTHRYX AI.

Creates clearly labelled DEMO/SYNTHETIC records only:

- 1 subsidiary, 2 mines (approximate coalfield coordinates, marked
  ``coordinate_provenance=DEMO`` unless a real one is explicitly known)
- 3 users (ADMIN, MINE_MANAGER, FIELD_INSPECTOR), demo credentials
- A small proof-of-concept set of real CMR 2017 / Mines Act statutory
  rules (the same seed set documented in Phase 0's own plan - this
  script does not invent new statutory text, it seeds what is already
  documented elsewhere in this project)
- MineObligation rows so the M0 compliance page has something to show
- Zero MSHA rows, zero Q679/Q181 rows - never inserted as if they were
  Indian mine-level operational data

Safe to run any number of times: every insert is keyed on a natural
unique field (email, mine code, rule_code) and is skipped if it already
exists, never duplicated.

Run:
    python3 scripts/bootstrap_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app import database  # noqa: E402
from models.enums import (  # noqa: E402
    ClauseVerification, DataProvenance, MineType, ObligationStatus,
    ObligationType, Role, Severity,
)
from models.identity import User  # noqa: E402
from models.organisation import Mine, Subsidiary  # noqa: E402
from models.statutory import MineObligation, StatutoryRule  # noqa: E402
from services.security import hash_password  # noqa: E402

DEMO_MARKER = "DEMO/SYNTHETIC - created by scripts/bootstrap_demo.py, not a real mine or person"

DEMO_USERS = [
    {"email": "demo.admin@example.com", "full_name": "Demo Admin", "role": Role.ADMIN,
     "password": "DemoAdmin123!"},
    {"email": "demo.manager@example.com", "full_name": "Demo Mine Manager", "role": Role.MINE_MANAGER,
     "password": "DemoManager123!"},
    {"email": "demo.inspector@example.com", "full_name": "Demo Field Inspector", "role": Role.FIELD_INSPECTOR,
     "password": "DemoInspector123!"},
]

# Approximate coalfield locations - explicitly DEMO provenance, never
# claimed as surveyed mine boundaries. Coordinates are real coalfield
# regions but the mine record itself is a demo entity, not a real,
# specific, currently operating mine.
DEMO_MINES = [
    {"code": "DEMO-JHR-01", "name": "Demo Colliery — Jharia Coalfield", "mine_type": MineType.UNDERGROUND,
     "state": "Jharkhand", "latitude": 23.7392, "longitude": 86.4141, "average_employee_count": 340},
    {"code": "DEMO-KRB-01", "name": "Demo Opencast — Korba Coalfield", "mine_type": MineType.OPENCAST,
     "state": "Chhattisgarh", "latitude": 22.3595, "longitude": 82.7501, "average_employee_count": 610},
    {"code": "DEMO-RAN-01", "name": "Demo Colliery — Raniganj Coalfield", "mine_type": MineType.UNDERGROUND,
     "state": "West Bengal", "latitude": 23.6167, "longitude": 87.1167, "average_employee_count": 210},
    {"code": "DEMO-TAL-01", "name": "Demo Opencast — Talcher Coalfield", "mine_type": MineType.OPENCAST,
     "state": "Odisha", "latitude": 20.9500, "longitude": 85.2167, "average_employee_count": 480},
    {"code": "DEMO-SGR-01", "name": "Demo Colliery — Singrauli Coalfield", "mine_type": MineType.UNDERGROUND,
     "state": "Madhya Pradesh", "latitude": 24.1994, "longitude": 82.6747, "average_employee_count": 95},
]

# Deliberately varied compliance/telemetry posture per mine, so a
# reviewer sees the full risk spectrum on first login rather than one
# flat state. Every finding/reading below is real, application-created
# data - never a frontend-only number.
DEMO_MINE_POSTURE = {
    "DEMO-JHR-01": {"non_compliant_findings": 6, "finding_severity": Severity.HIGH, "telemetry_mode": "anomaly"},
    "DEMO-KRB-01": {"non_compliant_findings": 2, "finding_severity": Severity.MEDIUM, "telemetry_mode": "normal"},
    "DEMO-RAN-01": {"non_compliant_findings": 0, "finding_severity": None, "telemetry_mode": "normal"},
    "DEMO-TAL-01": {"non_compliant_findings": 4, "finding_severity": Severity.HIGH, "telemetry_mode": "anomaly"},
    "DEMO-SGR-01": {"non_compliant_findings": 1, "finding_severity": Severity.LOW, "telemetry_mode": "normal"},
}

# Proof-of-concept statutory rules. Real CMR 2017 / Mines Act 1952
# references, matching this project's own documented seed set - not
# invented statutory text, and explicitly not claimed as the full corpus.
DEMO_RULES = [
    {"rule_code": "CMR-104", "statute": "Coal Mines Regulations 2017", "clause": "Regulation 104",
     "title": "Safety Management Plan — hazard identification and risk assessment",
     "obligation_type": ObligationType.CERTIFICATE_VALIDITY, "frequency_days": 365,
     "applies_to_underground": True, "applies_to_opencast": True, "severity": Severity.CRITICAL,
     "evidence_required": "Approved Safety Management Plan document", "authority": "DGMS"},
    {"rule_code": "CMR-129", "statute": "Coal Mines Regulations 2017", "clause": "Regulation 129",
     "title": "Ventilation standards", "obligation_type": ObligationType.RECURRING_MEETING,
     "frequency_days": 60, "applies_to_underground": True, "applies_to_opencast": False,
     "severity": Severity.HIGH, "evidence_required": "Ventilation survey record", "authority": "DGMS"},
    {"rule_code": "CMR-146", "statute": "Coal Mines Regulations 2017", "clause": "Regulation 146",
     "title": "Dust suppression", "obligation_type": ObligationType.RECURRING_MEETING,
     "frequency_days": 30, "applies_to_underground": True, "applies_to_opencast": True,
     "severity": Severity.MEDIUM, "evidence_required": "Water spray log", "authority": "DGMS"},
    {"rule_code": "CMR-214", "statute": "Coal Mines Regulations 2017", "clause": "Regulation 214",
     "title": "Safety Committee meetings", "obligation_type": ObligationType.RECURRING_MEETING,
     "frequency_days": 60, "applies_to_underground": True, "applies_to_opencast": True,
     "severity": Severity.HIGH, "evidence_required": "Meeting minutes", "authority": "DGMS"},
    {"rule_code": "MA-19", "statute": "Mines Act 1952", "clause": "Section 19",
     "title": "Drinking water provision", "obligation_type": ObligationType.RECURRING_MEETING,
     "frequency_days": 90, "applies_to_underground": True, "applies_to_opencast": True,
     "severity": Severity.MEDIUM, "evidence_required": "Facility inspection record", "authority": "DGMS"},
]


def bootstrap() -> dict:
    session = database.get_sessionmaker()()
    summary = {"subsidiaries": 0, "mines": 0, "users": 0, "rules": 0, "obligations": 0, "skipped": []}

    try:
        sub = session.execute(select(Subsidiary).where(Subsidiary.code == "DEMO-SUB")).scalar_one_or_none()
        if sub is None:
            sub = Subsidiary(code="DEMO-SUB", name=f"Demo Subsidiary ({DEMO_MARKER})", state="Jharkhand")
            session.add(sub); session.flush()
            summary["subsidiaries"] += 1
        else:
            summary["skipped"].append("subsidiary DEMO-SUB already exists")

        mine_rows = []
        for m in DEMO_MINES:
            existing = session.execute(select(Mine).where(Mine.code == m["code"])).scalar_one_or_none()
            if existing is not None:
                mine_rows.append(existing)
                summary["skipped"].append(f"mine {m['code']} already exists")
                continue
            mine = Mine(
                subsidiary_id=sub.id, coordinate_is_approximate=True,
                coordinate_provenance=DataProvenance.DEMO,
                coordinate_note=f"Approximate coalfield location. {DEMO_MARKER}",
                **m,
            )
            session.add(mine); session.flush()
            mine_rows.append(mine)
            summary["mines"] += 1

        for u in DEMO_USERS:
            existing = session.execute(select(User).where(User.email == u["email"])).scalar_one_or_none()
            if existing is not None:
                summary["skipped"].append(f"user {u['email']} already exists")
                continue
            user_kwargs = dict(
                email=u["email"], full_name=u["full_name"], role=u["role"],
                password_hash=hash_password(u["password"]),
            )
            if u["role"] != Role.ADMIN:
                user_kwargs["mine_id"] = mine_rows[0].id
                user_kwargs["subsidiary_id"] = sub.id
            session.add(User(**user_kwargs))
            summary["users"] += 1
        session.flush()

        rule_rows = []
        for r in DEMO_RULES:
            existing = session.execute(
                select(StatutoryRule).where(StatutoryRule.rule_code == r["rule_code"])
            ).scalar_one_or_none()
            if existing is not None:
                rule_rows.append(existing)
                summary["skipped"].append(f"rule {r['rule_code']} already exists")
                continue
            rule = StatutoryRule(clause_verification=ClauseVerification.UNVERIFIED, **r)
            session.add(rule); session.flush()
            rule_rows.append(rule)
            summary["rules"] += 1

        for mine in mine_rows:
            applies_col = "applies_to_underground" if mine.mine_type == MineType.UNDERGROUND else "applies_to_opencast"
            for rule in rule_rows:
                if not getattr(rule, applies_col):
                    continue
                existing = session.execute(
                    select(MineObligation).where(
                        MineObligation.mine_id == mine.id, MineObligation.rule_id == rule.id
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    continue
                session.add(MineObligation(mine_id=mine.id, rule_id=rule.id, status=ObligationStatus.MISSING))
                summary["obligations"] += 1

        session.commit()

        # --- demo inspection findings, telemetry, and real M3 scoring ---
        # Everything below is genuine application data created through the
        # same models/services the live API uses - never a frontend-only
        # number. Idempotent: guarded per mine so re-running never
        # duplicates findings or piles up telemetry readings.
        from datetime import datetime, timezone
        from models.enums import EvidenceKind, LocationMethod, SyncStatus
        from models.field_evidence import FieldEvidence, InspectionFinding
        from services.telemetry_simulator import generate_readings
        from models.environment import EnvironmentalReading
        from services.feature_builder import FeatureBuilder
        from ml.m3_service import get_m3_scoring_service, M3NotAvailable

        summary["demo_findings"] = 0
        summary["demo_telemetry_readings"] = 0
        summary["demo_features_built"] = 0
        summary["demo_scores"] = 0

        for mine in mine_rows:
            posture = DEMO_MINE_POSTURE.get(mine.code)
            if posture is None:
                continue

            already_inspected = session.execute(
                select(FieldEvidence).where(
                    FieldEvidence.mine_id == mine.id, FieldEvidence.kind == EvidenceKind.INSPECTION,
                    FieldEvidence.client_uuid == f"bootstrap-{mine.code}-inspection",
                )
            ).scalar_one_or_none()
            if already_inspected is None and posture["non_compliant_findings"] > 0:
                ev = FieldEvidence(
                    client_uuid=f"bootstrap-{mine.code}-inspection", kind=EvidenceKind.INSPECTION,
                    mine_id=mine.id, server_timestamp=datetime.now(timezone.utc),
                    location_method=LocationMethod.NONE, sync_status=SyncStatus.SYNCED,
                )
                session.add(ev); session.flush()
                for i in range(posture["non_compliant_findings"]):
                    session.add(InspectionFinding(
                        evidence_id=ev.id, question=f"Demo checklist item {i + 1}",
                        compliant=False, severity=posture["finding_severity"],
                        observation=f"{DEMO_MARKER} - illustrative non-compliance for demo risk variety",
                    ))
                session.flush()
                summary["demo_findings"] += posture["non_compliant_findings"]

            existing_readings = session.execute(
                select(EnvironmentalReading).where(EnvironmentalReading.mine_id == mine.id).limit(1)
            ).scalar_one_or_none()
            if existing_readings is None:
                readings = generate_readings(mine.id, mode=posture["telemetry_mode"], seed=hash(mine.code) % 10000)
                for r in readings:
                    session.add(EnvironmentalReading(
                        mine_id=mine.id, sensor_kind=r.sensor_kind, value=r.value, unit=r.unit,
                        recorded_at=r.recorded_at, provenance=DataProvenance.SIMULATED,
                    ))
                session.flush()
                summary["demo_telemetry_readings"] += len(readings)

        session.commit()

        try:
            scorer = get_m3_scoring_service()
        except M3NotAvailable:
            scorer = None

        for mine in mine_rows:
            builder = FeatureBuilder(session)
            feature_row, _ = builder.build(mine.id)
            session.commit()
            summary["demo_features_built"] += 1
            if scorer is not None:
                scorer.score_and_persist(session, feature_row, mode="deployable")
                session.commit()
                summary["demo_scores"] += 1

        # --- demo grievances, approvals, and a contractor - real rows,
        # keyed so re-running never duplicates them ---
        from datetime import timedelta
        from models.grievance import Grievance, GrievanceEvent, GrievanceStatus
        from models.approval import ApprovalChain, ApprovalStep, STAGE_ORDER
        from models.documents import Contractor, ContractorSite
        from models.capa import CapaItem
        from models.enums import CapaSourceType, CapaStatus, GrievanceCategory, Severity

        summary["demo_grievances"] = 0
        summary["demo_approvals"] = 0
        summary["demo_contractors"] = 0

        first_mine = mine_rows[0]
        existing_grievance = session.execute(
            select(Grievance).where(Grievance.mine_id == first_mine.id, Grievance.description.like(f"{DEMO_MARKER}%"))
        ).scalar_one_or_none()
        if existing_grievance is None:
            g = Grievance(
                mine_id=first_mine.id, category=GrievanceCategory.SAFETY_CONCERN,
                description=f"{DEMO_MARKER} - haul road berm reported washed out after rain",
                is_anonymous=True, filed_by=None, status=GrievanceStatus.OPEN,
                sla_due_at=datetime.now(timezone.utc) - timedelta(days=1),  # already overdue, for demo visibility
            )
            session.add(g); session.flush()
            session.add(GrievanceEvent(grievance_id=g.id, from_status=None, to_status=GrievanceStatus.OPEN))
            session.flush()
            summary["demo_grievances"] += 1

        existing_contractor = session.execute(
            select(Contractor).where(Contractor.code == "DEMO-CTR-01")
        ).scalar_one_or_none()
        if existing_contractor is None:
            contractor = Contractor(code="DEMO-CTR-01", name="Demo Earthmovers Pvt Ltd (DEMO/SYNTHETIC)",
                                    trade="Overburden removal", status="ACTIVE",
                                    registered_on=datetime.now(timezone.utc).date())
            session.add(contractor); session.flush()
            session.add(ContractorSite(contractor_id=contractor.id, mine_id=first_mine.id, is_active=True))
            session.flush()
            summary["demo_contractors"] += 1

        existing_capa_for_approval = session.execute(
            select(CapaItem).where(CapaItem.mine_id == first_mine.id, CapaItem.description.like(f"{DEMO_MARKER}%"))
        ).scalar_one_or_none()
        if existing_capa_for_approval is None:
            capa = CapaItem(mine_id=first_mine.id, source_type=CapaSourceType.INCIDENT,
                            severity=Severity.CRITICAL, status=CapaStatus.OPEN,
                            description=f"{DEMO_MARKER} - major remediation spend requiring sign-off")
            session.add(capa); session.flush()
            chain = ApprovalChain(capa_id=capa.id, reason=f"{DEMO_MARKER} - illustrative approval chain")
            session.add(chain); session.flush()
            for i, stage in enumerate(STAGE_ORDER):
                session.add(ApprovalStep(chain_id=chain.id, sequence=i, stage=stage))
            session.flush()
            summary["demo_approvals"] += 1

        session.commit()

    finally:
        session.close()

    return summary


if __name__ == "__main__":
    import subprocess

    print("Running migrations...")
    subprocess.run(["python3", "-m", "alembic", "upgrade", "head"],
                   cwd=str(Path(__file__).resolve().parents[1]), check=True)

    print("Bootstrapping demo data (idempotent)...")
    result = bootstrap()
    print(f"Created: {result['subsidiaries']} subsidiary, {result['mines']} mines, "
         f"{result['users']} users, {result['rules']} rules, {result['obligations']} obligations")
    print(f"Demo data: {result['demo_findings']} inspection findings, "
         f"{result['demo_telemetry_readings']} SIMULATED telemetry readings, "
         f"{result['demo_features_built']} MlFeature rows built, "
         f"{result['demo_scores']} real M3 scores computed, "
         f"{result['demo_grievances']} grievances, {result['demo_approvals']} approval chains, "
         f"{result['demo_contractors']} contractors")
    if result["skipped"]:
        print(f"Skipped (already present): {len(result['skipped'])} items")
    print("\nDemo login credentials:")
    for u in DEMO_USERS:
        print(f"  {u['role'].value:20} {u['email']:30} {u['password']}")
    print(f"\nAll records above are {DEMO_MARKER.split(' - ')[0]}.")
    print("The application is now usable: start the backend and Streamlit, then log in.")

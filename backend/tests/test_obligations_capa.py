"""M0 obligation evaluation and M4 CAPA lifecycle."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from models.capa import CapaItem
from models.enums import (
    CapaSourceType, CapaStatus, ObligationStatus, Severity,
)
from models.statutory import MineObligation
from services import capa as capa_service
from services import obligations as obligation_service


def _obligation(next_due=None):
    return MineObligation(next_due_date=next_due)


TODAY = date(2026, 6, 1)


def test_no_evidence_ever_is_missing_not_valid():
    """The case no document-tracking system surfaces."""
    result = obligation_service.evaluate(_obligation(), TODAY, has_verified_evidence=False)
    assert result.status is ObligationStatus.MISSING
    assert "never" in result.reason or "no evidence" in result.reason


def test_past_due_with_no_evidence_is_still_missing():
    result = obligation_service.evaluate(
        _obligation(TODAY - timedelta(days=10)), TODAY, has_verified_evidence=False
    )
    assert result.status is ObligationStatus.MISSING


def test_uploaded_but_unverified_is_not_valid():
    """OCR extraction is never compliance verification."""
    result = obligation_service.evaluate(
        _obligation(TODAY + timedelta(days=200)), TODAY,
        has_verified_evidence=False, has_unverified_evidence=True,
    )
    assert result.status is ObligationStatus.PENDING_VERIFICATION


def test_verified_and_far_from_due_is_valid():
    result = obligation_service.evaluate(
        _obligation(TODAY + timedelta(days=90)), TODAY, has_verified_evidence=True
    )
    assert result.status is ObligationStatus.VALID


def test_within_thirty_days_is_expiring_soon():
    result = obligation_service.evaluate(
        _obligation(TODAY + timedelta(days=10)), TODAY, has_verified_evidence=True
    )
    assert result.status is ObligationStatus.EXPIRING_SOON
    assert result.days_until_due == 10


def test_past_due_with_verified_evidence_is_expired():
    result = obligation_service.evaluate(
        _obligation(TODAY - timedelta(days=5)), TODAY, has_verified_evidence=True
    )
    assert result.status is ObligationStatus.EXPIRED
    assert result.days_until_due == -5


def test_boundary_exactly_thirty_days():
    result = obligation_service.evaluate(
        _obligation(TODAY + timedelta(days=30)), TODAY, has_verified_evidence=True
    )
    assert result.status is ObligationStatus.EXPIRING_SOON


# --- M4 ---------------------------------------------------------------
def _capa(db_session, **kw):
    import uuid
    item = CapaItem(
        mine_id=kw.pop("mine_id", uuid.uuid4()),
        source_type=CapaSourceType.INCIDENT,
        description="test item",
        severity=kw.pop("severity", Severity.HIGH),
        status=kw.pop("status", CapaStatus.OPEN),
        **kw,
    )
    db_session.add(item)
    db_session.flush()
    return item


def test_happy_path_lifecycle(db_session):
    item = _capa(db_session)
    for target, kwargs in [
        (CapaStatus.ASSIGNED, {}),
        (CapaStatus.IN_PROGRESS, {}),
        (CapaStatus.EVIDENCE_SUBMITTED, {"evidence_doc_id": __import__("uuid").uuid4()}),
        (CapaStatus.VERIFIED, {"note": "inspected and confirmed"}),
        (CapaStatus.CLOSED, {"note": "closed out"}),
    ]:
        capa_service.transition(db_session, item, target, **kwargs)
    assert item.status is CapaStatus.CLOSED
    assert item.progress_percent == 100
    assert [e.to_status for e in item.events][-1] is CapaStatus.CLOSED


def test_cannot_skip_from_open_to_closed(db_session):
    item = _capa(db_session)
    with pytest.raises(capa_service.InvalidTransition):
        capa_service.transition(db_session, item, CapaStatus.CLOSED, note="x")


def test_evidence_submission_requires_evidence(db_session):
    item = _capa(db_session, status=CapaStatus.IN_PROGRESS)
    with pytest.raises(capa_service.InvalidTransition) as exc:
        capa_service.transition(db_session, item, CapaStatus.EVIDENCE_SUBMITTED)
    assert "evidence" in str(exc.value).lower()


def test_verification_requires_a_written_justification(db_session):
    import uuid
    item = _capa(db_session, status=CapaStatus.EVIDENCE_SUBMITTED)
    with pytest.raises(capa_service.InvalidTransition):
        capa_service.transition(db_session, item, CapaStatus.VERIFIED, note="  ")


def test_closed_is_terminal(db_session):
    item = _capa(db_session, status=CapaStatus.CLOSED)
    with pytest.raises(capa_service.InvalidTransition):
        capa_service.transition(db_session, item, CapaStatus.OPEN)


def test_every_transition_is_recorded(db_session):
    item = _capa(db_session)
    capa_service.transition(db_session, item, CapaStatus.ASSIGNED, note="to you")
    event = item.events[-1]
    assert event.from_status is CapaStatus.OPEN
    assert event.to_status is CapaStatus.ASSIGNED
    assert event.note == "to you"


def test_overdue_detection(db_session):
    item = _capa(db_session, due_date=TODAY - timedelta(days=1))
    assert item.is_overdue(TODAY) is True
    item.status = CapaStatus.CLOSED
    assert item.is_overdue(TODAY) is False


def test_escalation_ladder_climbs_with_lateness(db_session):
    item = _capa(db_session, due_date=TODAY)
    assert capa_service.due_escalation_level(item, TODAY - timedelta(days=10)) == 1
    assert capa_service.due_escalation_level(item, TODAY - timedelta(days=2)) == 2
    assert capa_service.due_escalation_level(item, TODAY) == 3
    assert capa_service.due_escalation_level(item, TODAY + timedelta(days=8)) == 4


def test_critical_severity_reaches_the_top_rung(db_session):
    item = _capa(db_session, due_date=TODAY + timedelta(days=30), severity=Severity.CRITICAL)
    assert capa_service.due_escalation_level(item, TODAY) == 4


def test_closed_items_do_not_escalate(db_session):
    item = _capa(db_session, due_date=TODAY - timedelta(days=60), status=CapaStatus.CLOSED)
    assert capa_service.due_escalation_level(item, TODAY) == 0

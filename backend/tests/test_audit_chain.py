"""Audit ledger: hash chain integrity and tamper detection."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.audit import (
    GENESIS_HASH, AuditLedger, LedgerRow, compute_row_hash, verify_rows,
)


def _append_some(ledger, n=5):
    for i in range(n):
        ledger.append(
            action=f"ACTION_{i}", entity_type="test", entity_id=str(i),
            actor_id=None, payload={"i": i},
        )


def test_chain_starts_at_genesis(db_session):
    ledger = AuditLedger(db_session)
    entry = ledger.append("FIRST", "test", "1")
    assert entry.seq == 1
    assert entry.prev_hash == GENESIS_HASH


def test_sequence_is_contiguous_and_links(db_session):
    ledger = AuditLedger(db_session)
    _append_some(ledger, 5)
    rows = ledger.all_rows()
    assert [r.seq for r in rows] == [1, 2, 3, 4, 5]
    for previous, current in zip(rows, rows[1:]):
        assert current.prev_hash == previous.row_hash


def test_intact_chain_verifies(db_session):
    ledger = AuditLedger(db_session)
    _append_some(ledger, 6)
    result = ledger.verify()
    assert result.intact is True
    assert result.entries_checked == 6
    assert result.broken_at_seq is None


def test_seq_is_inside_the_hash(db_session):
    """Renumbering a row must break verification.

    This is the specific weakness that leaving seq out of the hash would
    create, so it is tested directly rather than assumed.
    """
    a = compute_row_hash(
        1, None, "A", "t", "1", datetime(2026, 1, 1, tzinfo=timezone.utc),
        "{}", GENESIS_HASH,
    )
    b = compute_row_hash(
        2, None, "A", "t", "1", datetime(2026, 1, 1, tzinfo=timezone.utc),
        "{}", GENESIS_HASH,
    )
    assert a != b


def test_edited_interior_row_is_detected(db_session):
    ledger = AuditLedger(db_session)
    _append_some(ledger, 5)
    rows = ledger.all_rows()
    rows[2] = LedgerRow(**{**rows[2].__dict__, "action": "TAMPERED"})
    result = verify_rows(rows)
    assert result.intact is False
    assert result.broken_at_seq == 3


def test_deleted_interior_row_is_detected(db_session):
    ledger = AuditLedger(db_session)
    _append_some(ledger, 5)
    rows = ledger.all_rows()
    del rows[2]
    result = verify_rows(rows)
    assert result.intact is False


def test_payload_edit_is_detected(db_session):
    ledger = AuditLedger(db_session)
    _append_some(ledger, 4)
    rows = ledger.all_rows()
    rows[1] = LedgerRow(**{**rows[1].__dict__, "payload_json": '{"i":999}'})
    result = verify_rows(rows)
    assert result.intact is False
    assert result.broken_at_seq == 2


def test_tamper_drill_detects_without_writing(db_session):
    ledger = AuditLedger(db_session)
    _append_some(ledger, 5)
    before_count = ledger.count()

    outcome = ledger.tamper_drill(target_seq=3)

    assert outcome["ran"] is True
    assert outcome["database_modified"] is False
    assert outcome["detected"] is True
    assert outcome["after"]["broken_at_seq"] == 3
    # The real ledger must be untouched and still verify.
    assert ledger.count() == before_count
    assert ledger.verify().intact is True


def test_tamper_drill_on_empty_ledger_is_safe(db_session):
    outcome = AuditLedger(db_session).tamper_drill(1)
    assert outcome["ran"] is False
    assert outcome["database_modified"] is False


def test_canonical_payload_is_order_independent(db_session):
    from services.audit import canonical_payload

    assert canonical_payload({"b": 1, "a": 2}) == canonical_payload({"a": 2, "b": 1})


def test_verification_note_avoids_forbidden_claims(db_session):
    ledger = AuditLedger(db_session)
    ledger.append("X", "test")
    note = ledger.verify().as_dict()["note"].lower()
    assert "tamper-evident" in note
    assert "immutable" in note and "not immutable" in note
    assert "not a blockchain" in note

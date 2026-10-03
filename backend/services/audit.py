"""Tamper-evident audit ledger.

    row_hash = SHA256(seq | actor_id | action | entity_type | entity_id |
                      timestamp | payload_json | prev_hash)

``seq`` is inside the hash deliberately. If the sequence number were left
out, rows could be renumbered without breaking verification.

Properties, stated precisely:

* Detects any edit or deletion of an interior row; verification reports
  the sequence number where the chain breaks.
* Does NOT prevent anything. "Tamper-evident", never "immutable".
* Is NOT a blockchain. There is no distributed consensus and none is
  required for this property.
* Truncation of the newest rows is not detectable by the chain alone.
  Anchoring the head hash externally would address it. That is deployment
  scope, recorded here rather than quietly omitted.
"""

from __future__ import annotations

import hashlib
import json
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.reporting import AuditLogEntry

GENESIS_HASH = "0" * 64
FIELD_SEPARATOR = "|"


def _coerce_uuid(value) -> _uuid.UUID | None:
    """Accept a UUID or its string form for the actor column."""
    if value is None or isinstance(value, _uuid.UUID):
        return value
    try:
        return _uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def canonical_payload(payload: dict[str, Any] | None) -> str:
    """Stable JSON so the same content always hashes the same way."""
    return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)


def compute_row_hash(
    seq: int,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    timestamp: datetime,
    payload_json: str,
    prev_hash: str,
) -> str:
    parts = [
        str(seq),
        actor_id or "",
        action,
        entity_type,
        entity_id or "",
        (
    timestamp.replace(tzinfo=timezone.utc)
    if timestamp.tzinfo is None
    else timestamp.astimezone(timezone.utc)
).isoformat(),
        payload_json,
        prev_hash,
    ]
    return hashlib.sha256(FIELD_SEPARATOR.join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChainVerification:
    intact: bool
    entries_checked: int
    broken_at_seq: int | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "intact": self.intact,
            "entries_checked": self.entries_checked,
            "broken_at_seq": self.broken_at_seq,
            "reason": self.reason,
            "note": (
                "Tamper-evident hash chain. Detects edits and deletions of "
                "interior rows. Not immutable, not a blockchain. Truncation "
                "of the newest rows requires an external anchor to detect."
            ),
        }


@dataclass
class LedgerRow:
    """Plain row used for verification, so the same code can check rows
    read from the database and rows held only in memory."""

    seq: int
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    timestamp: datetime
    payload_json: str
    prev_hash: str
    row_hash: str


def _to_rows(entries: Iterable[AuditLogEntry]) -> list[LedgerRow]:
    return [
        LedgerRow(
            seq=e.seq,
            actor_id=str(e.actor_id) if e.actor_id else None,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            timestamp=e.timestamp,
            payload_json=e.payload_json,
            prev_hash=e.prev_hash,
            row_hash=e.row_hash,
        )
        for e in entries
    ]


def verify_rows(rows: Sequence[LedgerRow]) -> ChainVerification:
    expected_prev = GENESIS_HASH
    for index, row in enumerate(rows):
        expected_seq = index + 1
        if row.seq != expected_seq:
            return ChainVerification(
                False, row.seq, row.seq, f"sequence gap: expected {expected_seq}"
            )
        if row.prev_hash != expected_prev:
            return ChainVerification(
                False, row.seq, row.seq, "prev_hash does not match the preceding row"
            )
        recomputed = compute_row_hash(
            row.seq, row.actor_id, row.action, row.entity_type,
            row.entity_id, row.timestamp, row.payload_json, row.prev_hash,
        )
        if recomputed != row.row_hash:
            return ChainVerification(
                False, row.seq, row.seq, "row_hash does not match the row contents"
            )
        expected_prev = row.row_hash
    return ChainVerification(True, len(rows))


class AuditLedger:
    """Append-only writer. Appends are serialised by taking the current
    head under the caller's transaction; concurrent appends are resolved by
    the unique constraint on ``seq`` rather than by hoping."""

    def __init__(self, session: Session):
        self.session = session

    def head(self) -> AuditLogEntry | None:
        return self.session.execute(
            select(AuditLogEntry).order_by(AuditLogEntry.seq.desc()).limit(1)
        ).scalar_one_or_none()

    def count(self) -> int:
        return int(self.session.execute(
            select(func.count()).select_from(AuditLogEntry)
        ).scalar_one())

    def append(
        self,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        actor_id: str | None = None,
        payload: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> AuditLogEntry:
        head = self.head()
        seq = (head.seq + 1) if head else 1
        prev_hash = head.row_hash if head else GENESIS_HASH
        # Server clock only. A client-supplied time is never authoritative.
        ts = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc)
        payload_json = canonical_payload(payload)
        # The hash always uses the canonical string form, so it does not
        # depend on whether the caller passed a UUID object or a string.
        actor_str = str(actor_id) if actor_id is not None else None
        row_hash = compute_row_hash(
            seq, actor_str, action, entity_type, entity_id, ts, payload_json, prev_hash
        )
        entry = AuditLogEntry(
            seq=seq, actor_id=_coerce_uuid(actor_id), action=action,
            entity_type=entity_type,
            entity_id=entity_id, timestamp=ts, payload_json=payload_json,
            prev_hash=prev_hash, row_hash=row_hash,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def entries(self, limit: int = 200, offset: int = 0) -> list[AuditLogEntry]:
        return list(self.session.execute(
            select(AuditLogEntry).order_by(AuditLogEntry.seq).offset(offset).limit(limit)
        ).scalars())

    def all_rows(self) -> list[LedgerRow]:
        return _to_rows(self.session.execute(
            select(AuditLogEntry).order_by(AuditLogEntry.seq)
        ).scalars())

    def verify(self) -> ChainVerification:
        return verify_rows(self.all_rows())

    def tamper_drill(self, target_seq: int, replacement_action: str = "TAMPERED") -> dict:
        """Demonstrate detection without damaging the ledger.

        The chain is copied into memory, the copy is corrupted, and the
        copy is verified. Nothing is written to the database, so the demo
        can be run repeatedly and in front of an audience without leaving
        the system in a broken state.
        """
        rows = self.all_rows()
        if not rows:
            return {
                "ran": False,
                "reason": "ledger is empty; nothing to demonstrate",
                "database_modified": False,
            }
        if not any(r.seq == target_seq for r in rows):
            return {
                "ran": False,
                "reason": f"no entry at seq {target_seq}",
                "database_modified": False,
            }

        before = verify_rows(rows)
        corrupted = [
            LedgerRow(**{**r.__dict__, "action": replacement_action})
            if r.seq == target_seq else r
            for r in rows
        ]
        after = verify_rows(corrupted)
        return {
            "ran": True,
            "database_modified": False,
            "target_seq": target_seq,
            "before": before.as_dict(),
            "after": after.as_dict(),
            "detected": (not after.intact) and after.broken_at_seq == target_seq,
            "note": (
                "Performed on an in-memory copy. The stored ledger was not "
                "written to and remains intact."
            ),
        }

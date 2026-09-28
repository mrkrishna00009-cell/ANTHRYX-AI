"""Shared CAPA-trigger logic for M2 (inspection findings, incidents).

One function, called from both the inspection-finding path and the
regular form-based incident path, so the threshold and idempotency rule
live in exactly one place - the voice-incident endpoint already had its
own inline version of this logic; this module is the shared, canonical
form other callers use instead of duplicating it.

Threshold policy (unchanged from what voice-incident already did):
severity HIGH or CRITICAL triggers a CAPA. Nothing lower does.

Idempotency: a CAPA is keyed to its originating record
(``source_id``) - calling this twice for the same finding or incident
never creates a second CAPA for it. This is a different, narrower key
than M3's "one active CAPA per mine" rule, and deliberately so: two
different inspection findings on the same mine are two different real
problems and each deserves its own CAPA; the same finding retried
(e.g. a client retry after a timeout) must not become two.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.capa import CapaItem
from models.enums import CapaSourceType, CapaStatus, Severity
from services.audit import AuditLedger

TRIGGERING_SEVERITIES = (Severity.HIGH, Severity.CRITICAL)


def maybe_create_capa(
    session: Session,
    *,
    mine_id: uuid.UUID,
    source_type: CapaSourceType,
    source_id: uuid.UUID,
    severity: Severity | None,
    description: str,
    actor_id: uuid.UUID | str,
    rule_id: uuid.UUID | None = None,
) -> tuple[CapaItem | None, bool]:
    """Returns (capa_item_or_None, created_bool). Creates nothing if
    severity does not meet the threshold, or if a CAPA already exists for
    this exact source_id (idempotent retry)."""
    if severity not in TRIGGERING_SEVERITIES:
        return None, False

    existing = session.execute(
        select(CapaItem).where(
            CapaItem.source_type == source_type,
            CapaItem.source_id == source_id,
        ).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    capa = CapaItem(
        mine_id=mine_id, source_type=source_type, source_id=source_id,
        rule_id=rule_id, severity=severity, description=description,
        status=CapaStatus.OPEN,
    )
    session.add(capa)
    session.flush()
    AuditLedger(session).append(
        action="AUTO_CAPA_CREATED", entity_type="capa_item",
        entity_id=str(capa.id), actor_id=str(actor_id),
        payload={"mine_id": str(mine_id), "source_type": source_type.value,
                "source_id": str(source_id), "severity": severity.value},
    )
    return capa, True
